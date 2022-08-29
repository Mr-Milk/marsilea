from __future__ import annotations

import logging

log = logging.getLogger("heatgraphy")

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib import colors as mcolors
from matplotlib.axes import Axes
from matplotlib.figure import Figure

import seaborn as sns
from seaborn import despine

from sklearn.preprocessing import RobustScaler, MinMaxScaler

from .layout import Grid
from ._plotter import ColorMesh
from .dendrogram import Dendrogram


class Chart(Enum):
    Bar = "bar"
    Box = "box"
    Colors = "colors"
    Scatter = "scatter"
    Dendrogram = "dendrogram"
    Violin = "violin"
    Line = "line"


class Plot:
    ax: Any
    legend: Any


@dataclass
class RenderPlan:
    name: str
    side: str
    data: Any
    size: float
    chart: Chart


# x: col, y: row
class SplitPlan:
    """A helper class that does:
    1. Split the data based on index
    2. Reorder data chunks and data within chunk
    """
    data: np.ndarray
    split_col = False
    split_row = False
    _split_index_col: np.ndarray = None
    _split_index_row: np.ndarray = None
    wspace: float = 0.05
    hspace: float = 0.05

    def __init__(self, data):
        self.data = data
        self._nrow, self._ncol = data.shape

    def set_split_index(self, col=None, row=None):
        if col is not None:
            col = np.sort(np.asarray(col))
            self._split_index_col = col
            self.split_col = True

        if row is not None:
            row = np.sort(np.asarray(row))
            self._split_index_row = row
            self.split_row = True

    # @property
    # def split_index_x(self):
    #     return self._split_index_x

    # @split_index_x.setter
    # def split_index_x(self, v):
    #     v = np.sort(np.asarray(v))
    #     # if v[-1] >= self.data.shape[1]:
    #     #     raise IndexError("Cannot split more than the size of data")
    #     # else:
    #     self._split_index_x = v
    #     self.split_x = True
    #
    # @property
    # def split_index_y(self):
    #     return self._split_index_y
    #
    # @split_index_y.setter
    # def split_index_y(self, v):
    #     v = np.sort(np.asarray(v))
    #     # if v[-1] >= self._X:
    #     #     raise IndexError("Cannot split more than the size of data")
    #     # else:
    #     self._split_index_y = v
    #     self.split_y = True

    def split_data(self, data=None):
        if data is None:
            data = self.data
        split_data = []
        if self.split_col & self.split_row:
            # split x and y
            start_x = 0
            start_y = 0
            for iy in [*self.split_index_y, self._Y]:
                for ix in [*self.split_index_x, self._X]:
                    # print((start_y, iy), (start_x, ix))
                    split_data.append(
                        data[start_y:iy, start_x:ix]
                    )
                    start_x = ix
                start_x = 0
                start_y = iy
        else:
            if self.split_col:
                # split x
                start_x = 0
                for ix in [*self.split_index_x, self._X]:
                    split_data.append(
                        data[:, start_x:ix]
                    )
                    start_x = ix
            if self.split_row:
                # split y
                start_y = 0
                for iy in [*self.split_index_y, self._Y]:
                    split_data.append(
                        data[start_y:iy]
                    )
                    start_y = iy
        return split_data

    def split_other_x(self, data: np.ndarray):
        if self.split_col:
            split_data = []
            start_x = 0
            for ix in self.split_index_x:
                if data.ndim == 2:
                    chunk = data[:, start_x:ix]
                elif data.ndim == 1:
                    chunk = data[start_x:ix]
                else:
                    raise ValueError("Cannot split data more than 2d")
                split_data.append(chunk)
                start_x += ix
        else:
            return data

    def split_other_y(self, data: np.ndarray):
        if self.split_row:
            split_data = []
            start_y = 0
            for iy in self.split_index_y:
                if data.ndim == 2:
                    chunk = data[start_y:iy, :]
                elif data.ndim == 1:
                    chunk = data[start_y:iy]
                else:
                    raise ValueError("Cannot split data more than 2d")
                split_data.append(chunk)
                start_y += iy
        else:
            return data

    @property
    def split_ratio_x(self):
        if self.split_index_x is not None:
            # Reverse the ratio to match reversed data
            return self.split_index_x / self._X
        else:
            return None

    @property
    def split_ratio_y(self):
        if self.split_index_y is not None:
            return self.split_index_y / self._Y
        else:
            return None

    def reorder_row(self, indices):
        pass

    def reorder_col(self, indices):
        pass


class Heatmap:
    gird: Grid
    figure: Figure
    heatmap_axes: Axes | List[Axes]

    def __init__(self,
                 data: np.ndarray,
                 vmin=None,
                 vmax=None,
                 cmap=None,
                 center=None,
                 robust=None,
                 mask=None,
                 ):

        self.render_data = None
        self._process_cmap(cmap, center)
        self._get_render_data(data, vmin, vmax, robust)

        self._dens = {}

        self.grid = Grid()
        self._split_plan = SplitPlan(self.render_data)
        self._side_count = {"right": 0, "left": 0, "top": 0, "bottom": 0}
        self._render_plan = []

        self._split_x = None
        self._split_y = None
        self._split_x_ratio = None
        self._split_y_ratio = None
        self._split_data = None

    def _get_render_data(self, raw_data, vmin, vmax, robust):

        if isinstance(raw_data, pd.DataFrame):
            data = raw_data.to_numpy()
        else:
            try:
                # try to transform to ndarray
                raw_data = np.asarray(raw_data)
                data = raw_data
            except Exception:
                msg = f"Don't know how to process input data with type " \
                      f"{type(raw_data)}"
                raise TypeError(msg)

        # If vmin and vmax is set
        # Perform regular normalize
        orig_shape = data.shape
        data = data.flatten()

        if not robust:
            # Perform min max normalize
            dmin = np.nanmin(data)
            dmax = np.nanmax(data)
            self.vmin = dmin if vmin is None else vmin
            self.vmax = dmax if vmax is None else vmax
            #
            # vrange = self.vmax - self.vmin
            # std = data - dmin / (dmax - dmin)
            # scaled = std * vrange + self.vmin

            trans_data = data

        else:
            # Use robust scale
            if isinstance(robust, bool):
                # Use seaborn default
                robust = (2., 98.)
            else:
                # User input quantile range, eg. (5., 95.)
                robust = robust
            transformer = RobustScaler(quantile_range=robust)
            transformer.fit(data)
            trans_data = transformer.transform(data)
            self.vmin = np.nanmin(trans_data)
            self.vmax = np.nanmax(trans_data)
            self.center = transformer.center_
        # Map to origin shape
        # Flip to match origin style of dataframe
        self.render_data = trans_data.reshape(orig_shape)

    # Copy from seaborn/matrix.py
    def _process_cmap(self, cmap, center):
        if cmap is None:
            self.cmap = cm.get_cmap('RdBu')
        elif isinstance(cmap, str):
            self.cmap = cm.get_cmap(cmap)
        elif isinstance(cmap, list):
            self.cmap = mcolors.ListedColormap(cmap)
        else:
            self.cmap = cmap

        if center is not None:

            # Copy bad values
            # in mpl<3.2 only masked values are honored with "bad" color spec
            # (see https://github.com/matplotlib/matplotlib/pull/14257)
            bad = self.cmap(np.ma.masked_invalid([np.nan]))[0]

            # under/over values are set for sure when cmap extremes
            # do not map to the same color as +-inf
            under = self.cmap(-np.inf)
            over = self.cmap(np.inf)
            under_set = under != self.cmap(0)
            over_set = over != self.cmap(self.cmap.N - 1)

            vrange = max(self.vmax - center, center - self.vmin)
            normlize = mcolors.Normalize(center - vrange, center + vrange)
            cmin, cmax = normlize([self.vmin, self.vmax])
            cc = np.linspace(cmin, cmax, 256)
            self.cmap = mcolors.ListedColormap(self.cmap(cc))
            self.cmap.set_bad(bad)
            if under_set:
                self.cmap.set_under(under)
            if over_set:
                self.cmap.set_over(over)

    def split_row(self, cut=None, labels=None, order=None, spacing=0.05):
        self._split_plan.hspace = spacing
        if cut is not None:
            self._split_plan.split_index_y = cut

    def split_col(self, cut=None, labels=None, order=None, spacing=0.05):
        self._split_plan.wspace = spacing
        if cut is not None:
            self._split_plan.split_index_x = cut

    def _split(self, x=None, y=None, wspace=0.05, hspace=0.05):
        split_x = x is not None
        split_y = y is not None

        X, Y = self.render_data.shape
        if split_x:
            x = np.asarray(x)
            self._split_x = np.array([*x, X])
            self._split_x_ratio = np.sort(x) / X
        if split_y:
            y = np.asarray(y)
            self._split_y = np.array([*y, Y])
            self._split_y_ratio = np.sort(y) / Y
        self.grid.split("main", x=self._split_x_ratio, y=self._split_y_ratio,
                        wspace=wspace, hspace=hspace)

        log.debug(f"split_x: {split_x}\n"
                  f"split_y: {split_y}\n"
                  f"split_data: {len(self._split_data)}\n")

    def add_labels(self, side):
        """Add tick labels to the heatmap"""
        pass

    def set_title(self, row=None, col=None, main=None):
        pass

    def _get_plot_name(self, name, side, chart):
        self._side_count[side] += 1
        if name is None:
            return f"{chart}-{self._side_count[side]}"
        else:
            return name

    def _add_plot(self, side, plot_type, data, name=None, size=1):
        plot_name = self._get_plot_name(name, side, plot_type)
        self.grid.add_ax(side, name=plot_name, size=size)
        self._render_plan.append(
            RenderPlan(name=plot_name, side=side,
                       data=data, size=size, chart=plot_type)
        )

    def add_colors(self, side, data, name=None, size=1):
        self._add_plot(side, Chart.Colors, data, name, size)

    def add_dendrogram(
            self,
            side,
            name=None,
            method=None,
            metric=None,
            linkage=None,
            show=True,
            size=1,
    ):
        plot_name = self._get_plot_name(name, side, Chart.Dendrogram)
        self.grid.add_ax(side, name=plot_name, size=size)
        pos = "row"
        if side in ["right", "left"]:
            pos = "col"
        self._dens[pos] = dict(
            side=side,
            method=method,
            metric=metric,
        )

    def add_heatmap(self, data):
        pass

    def add_category(self):
        pass

    def add_scatter(self):
        pass

    def add_bar(self, side, data, name=None, size=1):
        plot_name = self._get_plot_name(name, side, Chart.Bar)
        self.grid.add_ax(side, name=plot_name)
        self._render_plan.append(
            RenderPlan(name=plot_name, side=side,
                       data=data, size=size, chart=Chart.Bar))

    def add_violin(self):
        pass

    def add_annotation(self, side, name=None):
        """
        Add custom annotation to the plot

        Parameters
        ----------


        """
        pass

    def get_ax(self, name):
        """Get a specific axes by name when available"""
        pass

    def get_heatmap_ax(self):
        """Return the axes that draw heatmap"""
        pass

    def auto_legend(self, side):
        """Draw legend based on the order of annotation"""
        pass

    def render(self,
               figure=None,
               wspace=0,
               hspace=0,
               ):
        if figure is None:
            self.figure = plt.figure()
        else:
            self.figure = figure
        split_plan = self._split_plan
        render_data = self.render_data
        if split_plan.split_col or split_plan.split_row:
            print(split_plan.split_ratio_x, split_plan.split_ratio_y)
            self.grid.split("main",
                            x=split_plan.split_ratio_x,
                            y=split_plan.split_ratio_y,
                            wspace=split_plan.wspace,
                            hspace=split_plan.hspace
                            )
            render_data = split_plan.split_data()
            # TODO: split ax for other render plan
            if len(self._dens) > 0:
                col_split_data = split_plan.split_other_x(self.render_data)
                row_split_data = split_plan.split_other_y(self.render_data)
                col_dendrogram = []
                for pos, den in self._dens:
                    if pos == "col":
                        for chunk in col_split_data:
                            Dendrogram(chunk)
                            col_dendrogram.append()
                            self.render_data = self.render_data[
                                aden.reorder_index]

                    else:
                        aden = Dendrogram(self.render_data.T)
                        self.render_data = self.render_data[:,
                                           aden.reorder_index]


        else:
            # If not split
            for side, den in self._dens:
                if side in ["left", "right"]:
                    aden = Dendrogram(self.render_data)
                    self.render_data = self.render_data[aden.reorder_index]

                else:
                    aden = Dendrogram(self.render_data.T)
                    self.render_data = self.render_data[:, aden.reorder_index]

        self.grid.freeze(figure=self.figure, wspace=wspace, hspace=hspace)
        self.heatmap_axes = self.grid.get_canvas_ax("main")
        ColorMesh(self.heatmap_axes,
                  render_data,
                  cmap=self.cmap,
                  vmin=self.vmin,
                  vmax=self.vmax
                  )

        # for plan in self._render_plan:
        #     ax = self.grid.get_ax(plan.name)
        #     if plan.chart == Chart.Bar:
        #         # ax.xaxis.set_tick_params(labelbottom=False)
        #         if plan.side == "top":
        #             ax = sns.barplot(x=np.arange(10), y=plan.data, ax=ax)
        #             despine(ax=ax, top=True, bottom=False, right=True, left=True)
        #             ax.set_xticks([])
        #             ax.set_yticks([])
        #     elif plan.chart == Chart.Colors:
        #         if plan.side == "top":
        #             ax.pcolormesh(plan.data, cmap="Set1")
        #             ax.set_axis_off()
