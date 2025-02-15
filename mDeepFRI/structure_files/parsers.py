from io import TextIOWrapper
from typing import Tuple

import numpy as np


def parse_pdb(
        file: TextIOWrapper) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse a PDB file.

    Args:
        file (TextIOWrapper): Open file instance.

    Returns:
        sequence (list): Aminoacid sequence.
    """
    sequence = []
    positions = []
    groups = []
    line = file.readline()
    while line != "":
        if line.startswith("TER"):
            break
        if line.startswith("ATOM"):
            if len(line) == 81:
                if line[76] != 'H' and line[17] != ' ':
                    sequence.append(line[17:20])
                    positions.append([line[30:38], line[38:46], line[46:54]])
                    groups.append(line[21:26])
        line = file.readline()

    sequence = np.array(sequence)
    positions = np.array(positions, dtype=np.float32)
    groups = np.array(groups)

    return sequence, positions, groups


def parse_mmcif(
        file: TextIOWrapper) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse a mmCIF file.

    Args:
        file (TextIOWrapper): Open file instance.

    Returns:
        sequence (np.array): Aminoacid sequence.
        positions (np.array): Positions of the atoms.
        groups (np.array): Groups of the atoms.
    """

    n_atoms = -1

    label_counter = -1
    line = file.readline()
    while line != "":
        if line.startswith('_refine_hist.pdbx_number_atoms_protein'):
            n = line.split()[-1]
            if n != '?' and n != '0':
                try:
                    n_atoms = int(n)
                except ValueError:
                    line = file.readline()
                    continue
                sequence = np.empty(n_atoms, dtype=np.dtype('<U3'))
                positions = np.empty((n_atoms, 3), dtype=np.float32)
                groups = np.empty(n_atoms, dtype=np.dtype('<U10'))

        if line.startswith('_atom_site.'):
            label_counter += 1
            if line.startswith('_atom_site.type_symbol '):
                atom_symbol = label_counter
            if line.startswith('_atom_site.label_asym_id '):
                assembly = label_counter
            if line.startswith('_atom_site.label_seq_id '):
                sequence_id = label_counter
            if line.startswith('_atom_site.label_comp_id '):
                residue = label_counter
            if line.startswith('_atom_site.Cartn_x '):
                x = label_counter
            if line.startswith('_atom_site.Cartn_y '):
                y = label_counter
            if line.startswith('_atom_site.Cartn_z '):
                z = label_counter

        line = file.readline()
        if line.startswith("ATOM"):
            if label_counter > 0:
                break

    if n_atoms > 0:
        index = 0
        while line != '':
            if line.startswith('loop_'):
                break
            if line.startswith('ATOM'):
                atom = line.split()
                if len(atom[residue]) == 3 and atom[atom_symbol] != "H":
                    sequence[index] = atom[residue]
                    groups[index] = ''.join(
                        [atom[assembly], atom[sequence_id]])
                    positions[index][0] = atom[x]
                    positions[index][1] = atom[y]
                    positions[index][2] = atom[z]
                    index += 1
                    if index == n_atoms:
                        break
            line = file.readline()
        sequence.resize(index)
        positions.resize((index, 3))
        groups.resize(index)
    else:
        while line != '':
            if line.startswith('loop_'):
                break
            if line.startswith('ATOM'):
                atom = line.split()
                if len(atom[residue]) == 3 and atom[atom_symbol] != "H":
                    sequence.append(atom[residue])
                    groups.append(''.join([atom[assembly], atom[sequence_id]]))
                    positions.append([atom[x], atom[y], atom[z]])
            line = file.readline()
        positions = np.array(positions, dtype=np.float32)

    return sequence, positions, groups
