#
# Copyright (c) 2019 Jonathan Weyn <jweyn@uw.edu>
#
# See the file LICENSE for your rights.
#

"""
Simple routines for evaluating the performance of a DLWP model.
"""

from DLWP.model import DataGenerator, Preprocessor
from DLWP.model import verify
from DLWP.util import load_model
import keras.backend as K
import numpy as np
import pandas as pd
import xarray as xr
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.gridspec as gs
from mpl_toolkits.basemap import Basemap


#%% User parameters

# Open the data file
root_directory = '/home/disk/wave2/jweyn/Data/DLWP'
predictor_file = '%s/cfs_1979-2010_hgt_500_NH_T2.nc' % root_directory

# Names of model files, located in the root_directory
models = ['dlwp_1979-2010_hgt_500_NH_T2F_CLSTM_16_5_2_PBC',
          'dlwp_1979-2010_hgt_500_NH_T2F_CLSTM_CONV_16_5_2',
          'dlwp_1979-2010_hgt_500_NH_T2F_CONVx5-upsample-dilate',
          'dlwp_1979-2010_hgt_500_NH_T2F_CONVx5-lstm-upsample-dilate']
model_labels = ['LSTM', 'CLSTM-CONV-2', 'CONVx5-upsample', 'CONVx5-upsample-lstm']


# Load the result of a barotropic model for comparison
baro_model_file = '%s/barotropic_2003-2006.nc' % root_directory
baro_ds = xr.open_dataset(baro_model_file, cache=False)
baro_ds = baro_ds.isel(lat=(baro_ds.lat >= 0.0))  # Northern hemisphere only

# Date(s) of plots: the initialization time
plot_dates = list(pd.date_range('2003-02-14', '2003-02-22', freq='D').to_pydatetime())
plot_forecast_hour = 24
model_dt = 6

# Variable and level index to plot; scaling option
variable_index = 0
level_index = 0
scale_variables = True

# Latitude / Longitude limits
latitude_range = [20., 80.]
longitude_range = [220., 300.]

# Plot options
plot_type = 'contour'
plot_errors = True
plot_colormap = 'YlGnBu_r'
plot_colorbars = False
contour_range = [4800, 6000]
contour_step = 60
error_maxmin = 240

# Output file and other small details
plot_directory = './Plots'
plot_file_name = 'MAP_24'
plot_file_type = 'pdf'


#%% Plot function

def make_plot(m, time, init, verif, forecasts, model_names, skip_plots=(), file_name=None):
    num_panels = len(forecasts) + 2
    num_rows = int(np.ceil(num_panels / 2))
    verif_time = time + timedelta(hours=plot_forecast_hour)

    fig = plt.figure()
    fig.set_size_inches(12, 5 * num_rows)
    gs1 = gs.GridSpec(num_rows, 2)
    gs1.update(wspace=0.10, hspace=0.10)

    plot_fn = getattr(m, plot_type)
    contours = np.arange(np.min(contour_range), np.max(contour_range), contour_step)
    diff = None

    def plot_panel(n, da, title):
        ax = plt.subplot(gs1[n])
        lons, lats = np.meshgrid(da.lon, da.lat)
        x, y = m(lons, lats)
        if diff is not None:
            m.pcolormesh(x, y, da.values - diff.values, vmin=-error_maxmin, vmax=error_maxmin, cmap='seismic',
                         alpha=0.4)
        cs = plot_fn(x, y, da.values, contours, cmap=plot_colormap)
        plt.clabel(cs, fmt='%1.0f')
        m.drawcoastlines()
        m.drawparallels(np.arange(0., 91., 30.))
        m.drawmeridians(np.arange(0., 361., 60.))
        ax.set_title(title)

    plot_panel(0, init, 'Initial (%s)' % datetime.strftime(time, '%HZ %e %b %Y'))
    plot_panel(1, verif, 'Verification (%s)' % datetime.strftime(verif_time, '%HZ %e %b %Y'))
    plot_num = 2
    for f, forecast in enumerate(forecasts):
        if f + 2 in skip_plots:
            plot_num += 1
        if plot_errors is not None:
            diff = verif
        plot_panel(plot_num, forecast, '%s (%s)' % (model_names[f], datetime.strftime(verif_time, '%HZ %e %b %Y')))
        plot_num += 1

    if file_name is not None:
        plt.savefig(file_name, bbox_inches='tight')
    plt.show()


#%% Load the data

if not isinstance(plot_dates, list):
    plot_dates = [plot_dates]

# Add verification dates to the dataset
sel_dates = list(plot_dates)
for date in plot_dates:
    verif_date = date + timedelta(hours=plot_forecast_hour)
    if verif_date not in sel_dates:
        sel_dates.append(verif_date)
sel_dates.sort()

# Use the predictor file as a wrapper
processor = Preprocessor(None, predictor_file=predictor_file)
processor.open()
dataset = processor.data.sel(sample=np.array(sel_dates, dtype='datetime64'))

lat_min = np.min(latitude_range)
lat_max = np.max(latitude_range)
lon_min = np.min(longitude_range)
lon_max = np.max(longitude_range)

# Get the mean and std of the data
var_idx = variable_index // dataset.dims['level']
lev_idx = variable_index % dataset.dims['level']
z500_mean = dataset.isel(variable=var_idx, level=lev_idx).variables['mean'].values
z500_std = dataset.isel(variable=var_idx, level=lev_idx).variables['std'].values


#%% Make forecasts

model_forecasts = []
num_forecast_steps = int(np.ceil(plot_forecast_hour / model_dt))
f_hour = np.arange(model_dt, num_forecast_steps * model_dt + 1, model_dt)
dlwp, p_val, t_val = None, None, None

for mod, model in enumerate(models):
    print('Loading model %s...' % model)
    dlwp, history = load_model('%s/%s' % (root_directory, model), True)

    # Create data generators. If the model has upsampling, remove a latitude index if the number of latitudes is odd
    if 'upsample' in model.lower():
        val_generator = DataGenerator(dlwp, dataset.isel(lat=slice(dataset.dims['lat'] % 2, None)), batch_size=216)
    else:
        val_generator = DataGenerator(dlwp, dataset, batch_size=216)
    p_val, t_val = val_generator.generate([], scale_and_impute=False)

    # Make a time series prediction and convert the predictors for comparison
    print('Predicting with model %s...' % model_labels[mod])
    time_series = dlwp.predict_timeseries(p_val, num_forecast_steps)
    if scale_variables:
        time_series = time_series * z500_std + z500_mean
    time_series = verify.add_metadata_to_forecast(time_series, f_hour, val_generator.ds)

    # Slice the array as we want it
    if variable_index is None:
        variable_index = slice(None)
    time_series = time_series.isel(variable=variable_index,
                                   lat=((time_series.lat >= lat_min) & (time_series.lat <= lat_max)),
                                   lon=((time_series.lon >= lon_min) & (time_series.lon <= lon_max)))

    model_forecasts.append(1. * time_series)

    # Clear the model
    dlwp, time_series, p_val, t_val = None, None, None, None
    K.clear_session()


#%% Add the barotropic model

if baro_ds is not None:
    baro = baro_ds.sel(f_hour=(baro_ds.f_hour <= plot_forecast_hour), time=plot_dates,
                       lat=((baro_ds.lat >= lat_min) & (baro_ds.lat <= lat_max)),
                       lon=((baro_ds.lon >= lon_min) & (baro_ds.lon <= lon_max)))
    baro.load()
    if not scale_variables:
        baro['Z'][:] = (baro['Z'] - z500_mean) / z500_std
    model_forecasts.append(baro['Z'])
    model_labels.append('Barotropic')


#%% Run the plots

basemap = Basemap(llcrnrlon=lon_min, llcrnrlat=lat_min, urcrnrlon=lon_max, urcrnrlat=lat_max,
                  resolution='l', projection='cyl', lat_0=40., lon_0=0.)

for date in plot_dates:
    print('Plotting for %s...' % date)
    date64 = np.datetime64(date)
    verif_date64 = date64 + np.timedelta64(timedelta(hours=plot_forecast_hour))

    plot_fields = [f.sel(f_hour=plot_forecast_hour, time=date64) for f in model_forecasts]

    init_data = dataset['predictors'].sel(sample=date64).isel(
        variable=variable_index, level=level_index, time_step=-1,
        lat=((dataset.lat >= lat_min) & (dataset.lat <= lat_max)),
        lon=((dataset.lon >= lon_min) & (dataset.lon <= lon_max)))
    verif_data = dataset['predictors'].sel(sample=verif_date64).isel(
        variable=variable_index, level=level_index, time_step=-1,
        lat=((dataset.lat >= lat_min) & (dataset.lat <= lat_max)),
        lon=((dataset.lon >= lon_min) & (dataset.lon <= lon_max)))

    if scale_variables:
        init_data = init_data * z500_std + z500_mean
        verif_data = verif_data * z500_std + z500_mean

    file_name_complete = '%s/%s_%s.%s' % (plot_directory, plot_file_name, datetime.strftime(date, '%Y%m%d%H'),
                                          plot_file_type)

    make_plot(basemap, date, init_data, verif_data, plot_fields, model_labels, file_name=file_name_complete)