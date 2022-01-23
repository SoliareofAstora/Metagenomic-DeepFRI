import argparse
import json
import multiprocessing
import os
import pathlib
import shutil

from Bio import SeqIO

from CONFIG.FOLDER_STRUCTURE import QUERY_PATH, WORK_PATH, FINISHED_PATH, DEFAULT_NAME, MERGED_SEQUENCES, TASK_CONFIG, \
    JOB_CONFIG, ALIGNMENTS

from CONFIG.RUNTIME_PARAMETERS import ALIGNMENT_MIN_SEQUENCE_IDENTITY, MMSEQS_MAX_EVAL, MMSEQS_MIN_BIT_SCORE, \
    PAIRWISE_ALIGNMENT_GAP_CONTINUATION, PAIRWISE_ALIGNMENT_GAP_OPEN, PAIRWISE_ALIGNMENT_MISSMATCH, \
    PAIRWISE_ALIGNMENT_MATCH, GENERATE_CONTACTS, ANGSTROM_CONTACT_THRESHOLD, MAX_QUERY_CHAIN_LENGTH, CPU_COUNT, \
    DEEPFRI_PROCESSING_MODES

from metagenomic_deepfri_pipeline import metagenomic_deepfri_pipeline
from utils.elapsed_time_logger import ElapsedTimeLogger
from utils.pipeline_utils import select_target_database, load_deepfri_config
from utils.utils import create_unix_timestamp_folder, merge_files_binary, search_files_in_paths, chunks


def parse_args():
    # todo add description
    parser = argparse.ArgumentParser(description="main pipeline")
    parser.add_argument("-n", "--task_name", required=False, default=DEFAULT_NAME, help="Task name")
    parser.add_argument("-q", "--query_paths", nargs='+', required=False, default=None,
                        help=f"Folders paths containing query .faa files and/or paths to .faa files. "
                             f"If not provided pipeline will search in {QUERY_PATH}/task_name. "
                             f"Use '-q all' to process all files within {QUERY_PATH}")
    parser.add_argument("-t", "--target_db_name", required=False, default=DEFAULT_NAME, help="Target database name")
    parser.add_argument("-d", "--delete_query", action="store_true",
                        help="Use this flag so that query files are deleted from --query_paths after being copied to task workspace")
    parser.add_argument("-p", "--parallel_jobs", required=False, default=1, type=int, help="Number of parallel jobs")
    return parser.parse_args()


def save_task_config(task_work_path, task_name, target_db, target_db_name):
    config = {
        "task_name": task_name,
        "target_db": str(target_db),
        "target_db_name": target_db_name,

        "DEEPFRI_PROCESSING_MODES": DEEPFRI_PROCESSING_MODES,

        "MAX_QUERY_CHAIN_LENGTH": MAX_QUERY_CHAIN_LENGTH,
        "ANGSTROM_CONTACT_THRESHOLD": ANGSTROM_CONTACT_THRESHOLD,
        "GENERATE_CONTACTS": GENERATE_CONTACTS,

        "PAIRWISE_ALIGNMENT_MATCH": PAIRWISE_ALIGNMENT_MATCH,
        "PAIRWISE_ALIGNMENT_MISSMATCH": PAIRWISE_ALIGNMENT_MISSMATCH,
        "PAIRWISE_ALIGNMENT_GAP_OPEN": PAIRWISE_ALIGNMENT_GAP_OPEN,
        "PAIRWISE_ALIGNMENT_GAP_CONTINUATION": PAIRWISE_ALIGNMENT_GAP_CONTINUATION,

        "MMSEQS_MIN_BIT_SCORE": MMSEQS_MIN_BIT_SCORE,
        "MMSEQS_MAX_EVAL": MMSEQS_MAX_EVAL,

        "ALIGNMENT_MIN_SEQUENCE_IDENTITY": ALIGNMENT_MIN_SEQUENCE_IDENTITY,
    }
    json.dump(config, open(task_work_path / TASK_CONFIG, "w"), indent=4)


def prepare_task(task_name, query_paths, target_db_name, delete_query):
    # check if deepfri model weights exists
    _ = load_deepfri_config()
    # find target mmseqs database
    target_db = select_target_database(target_db_name)

    query_faa_files = search_files_in_paths(query_paths, ".faa")
    if len(query_faa_files) == 0:
        print(f"No query protein sequences .faa files found inside {[str(x) for x in query_paths]}")
        return

    print(f"Query files to be processed: {len(query_faa_files)}")
    for file in query_faa_files:
        print(f"\t{file}")

    # create a new task_work_path for this task
    task_directory = WORK_PATH / task_name
    task_directory.mkdir(parents=True, exist_ok=True)
    task_work_path = create_unix_timestamp_folder(task_directory)
    print("Work path: ", task_work_path)

    # merge sequences from all the query files
    merged_queries_file = task_work_path / MERGED_SEQUENCES
    merge_files_binary(query_faa_files, merged_queries_file)
    # copy query files into task_work_path to have them saved in the results directory
    (task_work_path / "query_files").mkdir()
    for query_faa_file in query_faa_files:
        os.system(f"cp {query_faa_file} {task_work_path / 'query_files'}")
    # delete query files from query_paths if specified
    if delete_query:
        for query_path in query_faa_files:
            query_path.unlink()

    # save pipeline config in task_work_path
    save_task_config(task_work_path, task_name, target_db, target_db_name)

    return task_work_path


def split_task_into_jobs(task_work_path, parallel_jobs):
    assert task_work_path / MERGED_SEQUENCES, f"Missing {task_work_path / MERGED_SEQUENCES}"
    assert task_work_path / TASK_CONFIG, f"Missing {task_work_path / TASK_CONFIG}"

    with open(task_work_path / MERGED_SEQUENCES, "r") as f:
        query_records = [record for record in SeqIO.parse(f, "fasta")]

    jobs_records = chunks(query_records, parallel_jobs)
    for i in range(len(jobs_records)):
        if len(jobs_records[i]) == 0:
            continue
        job_path = (task_work_path / str(i))
        job_path.mkdir()
        os.system(f"cp {task_work_path / TASK_CONFIG} {job_path / JOB_CONFIG}")
        with open(job_path / "job_sequences.faa", "w") as f:
            for record in jobs_records[i]:
                f.write(f">{record.id}\n{record.seq}\n")


def parallel_pipelines(task_work_path):
    job_paths = [job.parent for job in task_work_path.glob(f"**/{JOB_CONFIG}")]
    with multiprocessing.Pool(min(len(job_paths), CPU_COUNT)) as p:
        p.map(metagenomic_deepfri_pipeline, job_paths)


def merge_finalized_task_results(task_work_path):
    assert task_work_path / TASK_CONFIG, f"Missing {task_work_path / TASK_CONFIG}"
    task_config = json.load(open(task_work_path / TASK_CONFIG))

    finished_path = FINISHED_PATH / task_config['task_name'] / task_work_path.name
    print("Finished! Saving output files to ", finished_path)
    finished_path.mkdir(parents=True)

    os.system(f"cp {task_work_path / TASK_CONFIG} {finished_path}")
    os.system(f"cp {task_work_path / MERGED_SEQUENCES} {finished_path}")
    os.system(f"cp -r {task_work_path}/query_files {finished_path}")
    os.system(f"cp {task_work_path}/metadata* {finished_path}")

    alignments = {}
    for alignment_file in list(task_work_path.glob(f"*/{ALIGNMENTS}")):
        alignments.update(json.load(open(alignment_file, "r")))
    json.dump(alignments, open(finished_path / ALIGNMENTS, "w"), indent=4, sort_keys=True)

    merge_files_binary(list(task_work_path.glob("*/mmseqs2_search_results.m8")), finished_path / "mmseqs2_search_results.m8")

    for deepfri_result in list(task_work_path.glob("*/results*")):
        if not (finished_path / deepfri_result.name).exists():
            os.system(f"cp {deepfri_result} {finished_path}")
            continue
        with open(deepfri_result, "r") as source:
            with open(finished_path / deepfri_result.name, "a") as dst:
                dst.writelines(source.readlines()[2:])

    for jobs_metadata_file in list(task_work_path.glob("*/metadata*")):
        metadata_store_path = finished_path / "jobs_metadata" / jobs_metadata_file.parent.name
        metadata_store_path.mkdir(parents=True, exist_ok=True)
        os.system(f"cp {jobs_metadata_file} {metadata_store_path}")


def main(task_name: str, query_paths: list, target_db_name: str, delete_query: bool, parallel_jobs: int):
    task_work_path = prepare_task(task_name, query_paths, target_db_name, delete_query)
    timer = ElapsedTimeLogger(task_work_path / "metadata_total_task_time.csv")

    split_task_into_jobs(task_work_path, parallel_jobs)
    parallel_pipelines(task_work_path)

    timer.log("metagenomic_deepfri_pipeline")
    merge_finalized_task_results(task_work_path)
    shutil.rmtree(task_work_path)


if __name__ == '__main__':
    args = parse_args()

    task_name = args.task_name
    target_db_name = args.target_db_name
    delete_query = args.delete_query
    parallel_jobs = args.parallel_jobs

    if args.query_paths is None:
        query_paths = [pathlib.Path(QUERY_PATH / task_name)]
    else:
        if args.query_paths == ["all"]:
            query_paths = [QUERY_PATH]
        else:
            query_paths = [pathlib.Path(x) for x in args.query_paths]

    main(task_name, query_paths, target_db_name, delete_query, parallel_jobs)
