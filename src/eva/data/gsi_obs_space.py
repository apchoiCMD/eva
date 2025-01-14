# (C) Copyright 2021-2022 NOAA/NWS/EMC
#
# (C) Copyright 2021-2022 United States Government as represented by the Administrator of the
# National Aeronautics and Space Administration. All Rights Reserved.
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.

# --------------------------------------------------------------------------------------------------

import os
import numpy as np
from itertools import groupby
from xarray import Dataset, open_dataset

from eva.data.eva_dataset_base import EvaDatasetBase
from eva.utilities.config import get
from eva.utilities.utils import parse_channel_list

# --------------------------------------------------------------------------------------------------


def all_equal(iterable):

    """
    Check if all elements in an iterable are equal.

    Args:
        iterable: An iterable object to check.

    Returns:
        bool: True if all elements are equal, False otherwise.
    """

    g = groupby(iterable)
    return next(g, True) and not next(g, False)


# --------------------------------------------------------------------------------------------------


def uv(group_vars):

    """
    Add 'uv' prefix to specified variables if present.

    Args:
        group_vars (list): List of variable names.

    Returns:
        list: List of variable names with 'uv' prefix added.
    """

    change_vars = ['Obs_Minus_Forecast_adjusted',
                   'Obs_Minus_Forecast_unadjusted',
                   'Observation']

    # Find if change variables are in group_vars
    good_vars = [x for x in change_vars if x in group_vars]

    # Loop through existing variables, add u_ and v_ versions
    for var in good_vars:
        group_vars.append('u_' + var)
        group_vars.append('v_' + var)

    # Drop existing variables without u/v suffix
    group_vars = list(set(group_vars) - set(good_vars))

    return group_vars


# --------------------------------------------------------------------------------------------------


def subset_channels(ds, channels, logger, add_channels_variable=False):

    """
    Subset the dataset based on specified channels.

    Args:
        ds (Dataset): The xarray Dataset to subset.
        channels (list): List of channel numbers to keep.
        logger (Logger): Logger instance for logging messages.
        add_channels_variable (bool, optional): Whether to add 'channelNumber' variable. Default is
        False.
    """

    if 'nchans' in list(ds.dims):

        # Number of user requested channels
        nchan_use = len(channels)

        # Number of channels in the file
        nchan_in_file = ds.nchans.size

        if nchan_use == 0:
            nchan_use = nchan_in_file

        if all(x in ds['sensor_chan'] for x in channels):
            ds = ds.sel(nchans=channels)

        else:
            bad_chans = [x for x in channels if x not in ds['sensor_chan']]

            logger.abort(f"{', '.join(str(i) for i in bad_chans)} was inputted as a channel " +
                         "but is not a valid entry. Valid channels include: \n" +
                         f"{', '.join(str(i) for i in ds['sensor_chan'].data)}")

    return ds


# --------------------------------------------------------------------------------------------------


def satellite_dataset(ds):

    """
    Build a new dataset to reshape satellite data.

    Args:
        ds (Dataset): The input xarray Dataset.

    Returns:
        Dataset: Reshaped xarray Dataset.
    """

    nchans = ds.dims['nchans']
    iters = int(ds.dims['nobs']/nchans)

    coords = {
        'nchans': (('nchans'), ds['sensor_chan'].data),
        'nobs': (('nobs'), np.arange(0, iters)),
        'BC_angord_arr_dim': (('BC_angord_arr_dim'), np.arange(0, 4))
    }

    data_vars = {}
    # Loop through each variable
    for var in ds.variables:

        # Ignore geovals data
        if var in ['air_temperature', 'air_pressure', 'air_pressure_levels',
                   'atmosphere_absorber_01', 'atmosphere_absorber_02', 'atmosphere_absorber_03']:
            continue

        # If variable has len of nchans, pass along data
        if len(ds[var]) == nchans:
            data_vars[var] = (('nchans'), ds[var].data)

        # If variable is BC_angord, reshape data
        elif var == 'BC_angord':
            data = np.reshape(ds['BC_angord'].data,
                              (iters, nchans, ds.dims['BC_angord_arr_dim']))
            data_vars[var] = (('nobs', 'nchans', 'BC_angord_arr_dim'), data)

        # Deals with how to handle nobs data
        else:
            # Check if values repeat over nchans
            condition = all_equal(ds[var].data[0:nchans])

            # If values are repeating over nchan iterations, keep as nobs
            if condition:
                data = ds[var].data[0::nchans]
                data_vars[var] = (('nobs'), data)

            # Else, reshape to be a 2d array
            else:
                data = np.reshape(ds[var].data, (iters, nchans))
                data_vars[var] = (('nobs', 'nchans'), data)

    # create dataset_config
    new_ds = Dataset(data_vars=data_vars,
                     coords=coords,
                     attrs=ds.attrs)

    return new_ds


# --------------------------------------------------------------------------------------------------


class GsiObsSpace(EvaDatasetBase):

    """
    Eva dataset class for processing GSI observation space data.
    """

    # ----------------------------------------------------------------------------------------------

    def execute(self, dataset_config, data_collections, timeing):

        """
        Execute the GSI observation space data processing.

        Args:
            dataset_config (dict): Configuration settings for the dataset processing.
            data_collections (DataCollections): Instance of the DataCollections class.
            timing (Timing): Timing instance for performance measurement.
        """

        # Get channels for radiances
        # --------------------------
        channels_str_or_list = get(dataset_config, self.logger, 'channels', [])

        # Convert channels to list
        channels = []
        if channels_str_or_list is not []:
            channels = parse_channel_list(channels_str_or_list, self.logger)

        # Filenames to be read into this collection
        # -----------------------------------------
        filenames = get(dataset_config, self.logger, 'filenames')

        # File variable type
        if 'satellite' in dataset_config:
            satellite = get(dataset_config, self.logger, 'satellite')
            sensor = get(dataset_config, self.logger, 'sensor')
        else:
            variable = get(dataset_config, self.logger, 'variable')

        # Get missing value threshold
        # ---------------------------
        threshold = float(get(dataset_config, self.logger, 'missing_value_threshold', 1.0e30))

        # Get the groups to be read
        # -------------------------
        groups = get(dataset_config, self.logger, 'groups')

        # Loop over filenames
        # -------------------
        for filename in filenames:

            # Loop over groups
            for group in groups:

                # Group name and variables
                group_name = get(group, self.logger, 'name')
                group_vars = get(group, self.logger, 'variables', 'all')

                # Set the collection name
                collection_name = dataset_config['name']

                ds = open_dataset(filename, mask_and_scale=False,
                                  decode_times=False)

                # If user specifies all variables set to group list
                if group_vars == 'all':
                    group_vars = list(ds.data_vars)

                # Reshape variables if satellite diag
                if 'nchans' in ds.dims:
                    ds = satellite_dataset(ds)
                    ds = subset_channels(ds, channels, self.logger)

                # Adjust variable names if uv
                if 'variable' in locals():
                    if variable == 'uv':
                        group_vars = uv(group_vars)

                # Check that all user variables are in the dataset_config
                if not all(v in list(ds.data_vars) for v in group_vars):
                    self.logger.abort('For collection \'' + dataset_config['name']
                                      + '\', group \'' + group_name + '\' in file ' + filename +
                                      f' . Variables {group_vars} not all present in ' +
                                      f'the data set variables: {list(ds.keys())}')

                # Drop data variables not in user requested variables
                vars_to_remove = list(set(list(ds.keys())) - set(group_vars))
                ds = ds.drop_vars(vars_to_remove)

                # Explicitly add the channels to the collection (we do not want to include this
                # in the 'variables' list in the YAML to avoid transforms being applied to them)
                if 'nchans' in ds.dims:
                    channels_used = ds['nchans']
                    ds[group_name + '::channelNumber'] = channels_used

                # Rename variables with group
                rename_dict = {}
                for group_var in group_vars:
                    rename_dict[group_var] = group_name + '::' + group_var
                ds = ds.rename(rename_dict)

                # Assert that the collection contains at least one variable
                if not ds.keys():
                    self.logger.abort('Collection \'' + dataset_config['name'] + '\', group \'' +
                                      group_name + '\' in file ' + filename +
                                      ' does not have any variables.')

            # Add the dataset_config to the collections
            data_collections.create_or_add_to_collection(collection_name, ds, 'nobs')

        # Nan out unphysical values
        data_collections.nan_float_values_outside_threshold(threshold)

        # Change the location dimension name
        data_collections.adjust_location_dimension_name('nobs')

        # Change the channel dimension name
        data_collections.adjust_channel_dimension_name('nchans')

    # ----------------------------------------------------------------------------------------------

    def generate_default_config(self, filenames, collection_name):

        """
        Generate the default configuration for the GSI observation space dataset.

        Args:
            filenames (list): List of filenames associated with the dataset.
            collection_name (str): Name of the collection.

        Returns:
            dict: Default configuration settings for the dataset.
        """

        # Create config template
        eva_dict = {'datasets': [{'filenames': filenames,
                                  'groups': [{'name': 'eva_interactive'}],
                                  'missing_value_threshold': 1.0e06,
                                  'name': collection_name}]}

        # Find either satellite/sensor or variable and add to config template
        eva_filename = filenames[0]
        name = eva_filename.split('.')[1]
        name_parts = name.split('_')
        if name_parts[0] == 'conv':
            variable = name_parts[1]
            eva_dict['datasets'][0]['variable'] = variable
        else:
            satellite = name_parts[1]
            sensor = name_parts[0]
            eva_dict['datasets'][0]['satellite'] = satellite
            eva_dict['datasets'][0]['sensor'] = sensor

        return eva_dict

    # ----------------------------------------------------------------------------------------------
