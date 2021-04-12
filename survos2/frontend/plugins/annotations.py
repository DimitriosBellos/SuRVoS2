import numpy as np
from loguru import logger
from matplotlib.colors import ListedColormap
from scipy.ndimage import binary_dilation
from skimage.draw import line
from skimage.morphology import disk

from survos2.frontend.components.base import *
from survos2.frontend.components.base import (
    FAIcon,
    HBox,
    LazyComboBox,
    LazyMultiComboBox,
    PluginNotifier,
    Slider,
)
from survos2.frontend.components.icon_buttons import DelIconButton, IconButton
from survos2.frontend.control.launcher import Launcher
from survos2.frontend.plugins.annotation_tool import (
    AnnotationComboBox,
    AnnotationTool,
    _AnnotationNotifier,
)
from survos2.frontend.plugins.base import *
from survos2.frontend.plugins.base import (
    ColorButton,
    ParentButton,
    Plugin,
    register_plugin,
)
from survos2.frontend.plugins.regions import RegionComboBox
from survos2.model import DataModel
from survos2.server.state import cfg

_AnnotationNotifier = PluginNotifier()


def dilate_annotations(yy, xx, img_shape, line_width):
    data = np.zeros(img_shape)
    data[yy, xx] = True

    r = np.ceil(line_width / 2)
    ymin = int(max(0, yy.min() - r))
    ymax = int(min(data.shape[0], yy.max() + 1 + r))
    xmin = int(max(0, xx.min() - r))
    xmax = int(min(data.shape[1], xx.max() + 1 + r))
    mask = data[ymin:ymax, xmin:xmax]

    mask = binary_dilation(mask, disk(line_width / 2).astype(np.bool))
    yy, xx = np.where(mask)
    yy += ymin
    xx += xmin
    return yy, xx


class LevelComboBox(LazyComboBox):
    def __init__(self, full=False, header=(None, "None"), parent=None):
        self.full = full
        self.except_level = None

        super().__init__(header=header, parent=parent)
        _AnnotationNotifier.listen(self.update)

    def fill(self):
        params = dict(workspace=True, full=self.full)
        result = Launcher.g.run("annotations", "get_levels", **params)
        print(self.except_level)
        if result:
            self.addCategory("Annotations")
            for r in result:
                level_name = r["name"]
                if level_name != self.except_level:
                    if r["kind"] == "level":
                        self.addItem(r["id"], r["name"])


@register_plugin
class AnnotationPlugin(Plugin):

    __icon__ = "fa.pencil"
    __pname__ = "annotations"
    __views__ = ["slice_viewer"]
    __tab__ = "annotations"

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.btn_addlevel = IconButton("fa.plus", "Add Level", accent=True)
        self.vbox = VBox(self, spacing=10)
        self.vbox.addWidget(self.btn_addlevel)
        self.levels = {}
        self.btn_addlevel.clicked.connect(self.add_level)
        self.annotation_tool = AnnotationTool()
        self.timer_id = -1

        hbox = HBox(self, margin=1, spacing=3)
        self.label = AnnotationComboBox()
        self.region = RegionComboBox(header=(None, "Voxels"), full=True)
        self.label.currentIndexChanged.connect(self.set_sv)

        self.region.currentIndexChanged.connect(self.set_sv)
        hbox.addWidget(self.label)
        hbox.addWidget(self.region)

        self.width = Slider(value=8, vmin=2, vmax=50, step=2)
        self.width.valueChanged.connect(self.set_sv)
        hbox.addWidget(self.width)
        hbox.addWidget(None, 1)

        self.vbox.addLayout(hbox)

        _AnnotationNotifier.listen(self.set_sv)

    def on_created(self):
        pass

    def add_level(self):
        level = Launcher.g.run("annotations", "add_level", workspace=True)
        if level:
            self._add_level_widget(level)
            _AnnotationNotifier.notify()

    def _add_level_widget(self, level):
        widget = AnnotationLevel(level)
        widget.removed.connect(self.remove_level)
        self.vbox.addWidget(widget)
        self.levels[level["id"]] = widget

    def uncheck_labels(self):
        for button in self.btn_group.buttons():
            selected = self.btn_group.checkedButton()
            button.setChecked(button is selected)

    def remove_level(self, level):
        if level in self.levels:
            self.levels.pop(level).setParent(None)
        _AnnotationNotifier.notify()

    def setup(self):
        result = Launcher.g.run("annotations", "get_levels", workspace=True)
        if not result:
            return

        # Remove levels that no longer exist in the server
        rlevels = [r["id"] for r in result]
        for level in list(self.levels.keys()):
            if level not in rlevels:
                self.remove_level(level)

        # Populate with new levels if any
        for level in result:
            if level["id"] not in self.levels:
                self._add_level_widget(level)


    def timerEvent(self, event):
        self.killTimer(self.timer_id)
        self.timer_id = -1
        self.set_sv()

    def slider_value_changed(self):
        if self.timer_id != -1:
            self.killTimer(self.timer_id)
        self.timer_id = self.startTimer(2000)

        

    def set_sv(self):
        cfg.current_supervoxels = self.region.value()
        cfg.label_value = self.label.value()
        cfg.brush_size = self.width.value()
        print(cfg.current_supervoxels, cfg.label_value)

        # example 'label_value': {'level': '001_level', 'idx': 2, 'color': '#ff007f'}
        cfg.ppw.clientEvent.emit(
            {
                "source": "annotations",
                "data": "set_paint_params",
                "paint_params": {
                    "current_supervoxels": self.region.value(),
                    "label_value": self.label.value(),
                    "brush_size": self.width.value(),
                },
            }
        )

        cfg.ppw.clientEvent.emit(
            {
                "source": "annotations",
                "data": "paint_annotations",
                "level_id": self.label.value()["level"],
            }
        )


class AnnotationLevel(Card):

    removed = QtCore.Signal(str)

    def __init__(self, level, parent=None):
        super().__init__(
            level["name"],
            editable=True,
            collapsible=True,
            removable=True,
            addbtn=True,
            parent=parent,
        )
        self.level_id = level["id"]
        self.le_title = LineEdit(level["name"])
        self.le_title.setProperty("header", True)
        self.labels = {}

        self._populate_labels()

    def card_title_edited(self, title):
        params = dict(level=self.level_id, name=title, workspace=True)
        return Launcher.g.run("annotations", "rename_level", **params)

    def card_add_item(self):
        params = dict(level=self.level_id, workspace=True)
        result = Launcher.g.run("annotations", "add_label", **params)
        self.view_level()
        if result:
            self._add_label_widget(result)
            _AnnotationNotifier.notify()

    def card_deleted(self):
        params = dict(level=self.level_id, workspace=True)
        result = Launcher.g.run("annotations", "delete_level", **params)
        if result:
            self.removed.emit(self.level_id)
            _AnnotationNotifier.notify()

        cfg.ppw.clientEvent.emit(
            {
                "source": "annotations",
                "data": "remove_layer",
                "layer_name": self.level_id,
            }
        )

    def remove_label(self, idx):
        if idx in self.labels:
            self.labels.pop(idx).setParent(None)
            self.update_height()

    def _add_label_widget(self, label):
        widget = AnnotationLabel(label, self.level_id)
        widget.removed.connect(self.remove_label)
        self.add_row(widget)
        self.labels[label["idx"]] = widget
        self.expand()

    def _populate_labels(self):
        params = dict(level=self.level_id, workspace=True)
        result = Launcher.g.run("annotations", "get_labels", **params)
        if result:
            for k, label in result.items():
                if k not in self.labels:
                    self._add_label_widget(label)

    def view_level(self):
        cfg.ppw.clientEvent.emit(
            {
                "source": "annotations",
                "data": "paint_annotations",
                "level_id": self.level_id,
            }
        )

    def _add_view_btn(self):
        btn_view = PushButton("View", accent=True)
        btn_view.clicked.connect(self.view_level)
        self.add_row(HWidgets(None, btn_view, Spacing(35)))


class AnnotationLabel(QCSWidget):

    __height__ = 30
    removed = QtCore.Signal(int)

    def __init__(self, label, level_dataset, parent=None):
        super().__init__(parent=parent)
        self.level_dataset = level_dataset
        self.label_idx = label["idx"]
        self.label_color = label["color"]
        self.label_name = label["name"]
        self.label_visible = label["visible"]
        self.level_number = int(level_dataset.split("_")[0])
        
        parent_level = -1
        parent_label = -1
        self.parent_level = parent_level
        self.parent_label = parent_label

        self.btn_del = DelIconButton(secondary=True)
        self.txt_label_name = LineEdit(label["name"])
        self.txt_idx = LineEdit(str(label["idx"]))
        self.btn_label_color = ColorButton(label["color"])
        self.btn_label_parent = ParentButton(color=None, source_level=self.level_dataset)
        # self.btn_select = IconButton("fa.pencil", "", accent=True)
        self.btn_label_parent.clicked.connect(self.set_parent)

        self.setMinimumHeight(self.__height__)
        self.setFixedHeight(self.__height__)
        self.txt_label_name.editingFinished.connect(self.update_label)
        self.btn_label_color.colorChanged.connect(self.update_label)
        self.btn_del.clicked.connect(self.delete)
        # self.btn_select.clicked.connect(self.set_label)

        hbox = HBox(self)
        hbox.addWidget(
            HWidgets(
                self.btn_del,
                str(label["idx"] - 1),
                self.btn_label_color,
                self.btn_label_parent,
                self.txt_label_name,
                # self.btn_select,
                stretch=4,
            )
        )

    def set_label(self):
        logger.debug(f"Setting label to {self.label_idx}")
        label_dict = {
            "level": self.level_dataset,
            "idx": self.label_idx,
            "color": self.label_color,
        }
        cfg.ppw.clientEvent.emit(
            {
                "source": "annotations",
                "data": "set_paint_params",
                "paint_params": {
                    "current_supervoxels": cfg.current_supervoxels,
                    "label_value": label_dict,
                    "brush_size": cfg.brush_size,
                },
            }
        )

    def set_parent(self):
        logger.debug(
            f"Setting parent level to {self.parent_level}, with label {self.parent_label}"
        )
        params = dict(
            workspace=True,
            level=self.level_dataset,
            label_idx=self.label_idx,
            parent_level=self.btn_label_parent.parent_level,
            parent_label_idx=self.btn_label_parent.parent_label,
        )
        result = Launcher.g.run("annotations", "set_label_parent", **params)

    # def parent_labels(self, level):
    #    return [label.parent_label for label in self._levels[level].values()]

    def update_label(self):
        label = dict(
            idx=self.label_idx,
            name=self.txt_label_name.text(),
            color=self.btn_label_color.color,
            visible=self.label_visible,
        )
        params = dict(level=self.level_dataset, workspace=True)
        result = Launcher.g.run("annotations", "update_label", **params, **label)

        if result:
            self.label_name = result["name"]
            self.label_color = result["color"]
            self.label_visible = result["visible"]
            _AnnotationNotifier.notify()
        else:
            self.txt_label_name.setText(self.label_name)
            self.btn_label_color.setColor(self.label_color)

    def delete(self):
        params = dict(level=self.level_dataset, workspace=True, idx=self.label_idx)
        result = Launcher.g.run("annotations", "delete_label", **params)
        if result:
            _AnnotationNotifier.notify()
            self.removed.emit(self.label_idx)
