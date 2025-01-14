# (C) Copyright 2024 NOAA/NWS/EMC
#
# (C) Copyright 2024 United States Government as represented by the Administrator of the
# National Aeronautics and Space Administration. All Rights Reserved.
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.

# --------------------------------------------------------------------------------------------------

import os
import netCDF4 as nc
import numpy as np
from xarray import Dataset, open_dataset
from eva.utilities.config import get
from eva.data.eva_dataset_base import EvaDatasetBase
from eva.utilities.utils import parse_channel_list


class GeovalSpace(EvaDatasetBase):

    """
    A class for handling geoval files
    """

    def execute(self, dataset_config, data_collections, timing):

        """
        Executes the processing of data file dataset.

        Args:
            dataset_config (dict): Configuration dictionary for the dataset.
            data_collections (DataCollections): Object for managing data collections.
            timing (Timing): Timing object for tracking execution time.
        """

        # Set the collection name
        # -----------------------
        collection_name = get(dataset_config, self.logger, 'name')

        # Get missing value threshold
        # ---------------------------
        threshold = float(get(dataset_config, self.logger, 'missing_value_threshold', 1.0e30))

        # Get levels to plot profiles
        # --------------------------_
        levels_str_or_list = get(dataset_config, self.logger, 'levels', [])

        # Convert levels to list
        levels = []
        if levels_str_or_list is not []:
            levels = parse_channel_list(levels_str_or_list, self.logger)

        # Filename to be used for reads
        # ---------------------------------------
        data_filename = get(dataset_config, self.logger, 'data_file')

        # Get instrument name
        instr_name = get(dataset_config, self.logger, 'instrument_name')

        # Open instrument files xarray dataset
        instr_ds = open_dataset(data_filename)

        # Enforce that a variable exists, do not default to all variables
        variables = get(dataset_config, self.logger, 'variables')
        if not variables:
            self.logger.abort('A variables list needs to be defined in the config file.')
        vars_to_remove = list(set(list(instr_ds.keys())) - set(variables))
        instr_ds = instr_ds.drop_vars(vars_to_remove)

        # Rename variables and nval dimension
        rename_dict = {}
        rename_dims_dict = {}
        for v in variables:
            # Retrieve dimension names
            dims = instr_ds[v].dims
            if np.size(dims) > 1:
                rename_dims_dict[dims[1]] = f'Level'
            rename_dict[v] = f'{instr_name}::{v}'
        instr_ds = instr_ds.rename(rename_dict)
        instr_ds = instr_ds.rename_dims(rename_dims_dict)

        # Add the dataset_config to the collections
        data_collections.create_or_add_to_collection(collection_name, instr_ds)

        # Nan out unphysical values
        data_collections.nan_float_values_outside_threshold(threshold)

    def generate_default_config(self, filenames, collection_name):

        """
        Generate a default configuration for the dataset.

        This method generates a default configuration for the dataset based on the provided
        filenames and collection name. It can be used as a starting point for creating a
        configuration for the dataset.

        Args:
            filenames: Filenames or file paths relevant to the dataset.
            collection_name (str): Name of the collection for the dataset.

        Returns:
            dict: A dictionary representing the default configuration for the dataset.
        """

        pass
