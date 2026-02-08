"""
Server view creation for the Dashboard.

This module contains the server management view UI creation,
extracted to keep the main dashboard.py file smaller.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)


def create_server_view(dashboard) -> QWidget:
    """Create the server management view.

    Args:
        dashboard: The DashboardWindow instance

    Returns:
        The server view widget
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    view = QWidget()
    view.setMinimumWidth(550)
    layout = QVBoxLayout(view)
    layout.setContentsMargins(40, 30, 40, 30)

    # Title
    title = QLabel("Docker Server")
    title.setObjectName("viewTitle")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(title)

    layout.addSpacing(20)

    card_width = 550

    # Status card
    status_frame = QFrame()
    status_frame.setObjectName("statusCard")
    status_frame.setFixedWidth(card_width)
    status_layout = QVBoxLayout(status_frame)
    status_layout.setSpacing(8)

    # Container status row
    container_row = QHBoxLayout()
    container_label = QLabel("Container:")
    container_label.setObjectName("statusLabel")
    container_row.addWidget(container_label)
    dashboard._server_status_label = QLabel("Checking...")
    dashboard._server_status_label.setObjectName("statusValue")
    container_row.addWidget(dashboard._server_status_label)
    container_row.addStretch()
    status_layout.addLayout(container_row)

    # Docker Image status row
    image_row = QHBoxLayout()
    image_label = QLabel("Docker Image:")
    image_label.setObjectName("statusLabel")
    image_row.addWidget(image_label)
    dashboard._image_status_label = QLabel("Checking...")
    dashboard._image_status_label.setObjectName("statusValue")
    image_row.addWidget(dashboard._image_status_label)
    dashboard._image_date_label = QLabel("")
    dashboard._image_date_label.setObjectName("statusDateInline")
    image_row.addWidget(dashboard._image_date_label)
    dashboard._image_size_label = QLabel("")
    dashboard._image_size_label.setObjectName("statusDateInline")
    image_row.addWidget(dashboard._image_size_label)
    image_row.addStretch()
    status_layout.addLayout(image_row)

    # Image selector row
    image_selector_row = QHBoxLayout()
    selector_label = QLabel("Select Image:")
    selector_label.setObjectName("statusLabel")
    image_selector_row.addWidget(selector_label)
    dashboard._image_selector = QComboBox()
    dashboard._image_selector.setObjectName("imageSelector")
    dashboard._image_selector.setMinimumWidth(280)
    dashboard._image_selector.setStyleSheet(
        "QComboBox { background-color: #2d2d2d; border: 1px solid #3d3d3d; "
        "border-radius: 6px; padding: 6px 10px; color: #e0e0e0; font-size: 12px; }"
        "QComboBox:hover { border-color: #505050; }"
        "QComboBox::drop-down { border: none; width: 20px; }"
        "QComboBox::down-arrow { image: none; border-left: 4px solid transparent; "
        "border-right: 4px solid transparent; border-top: 5px solid #808080; margin-right: 6px; }"
        "QComboBox QAbstractItemView { background-color: #2d2d2d; border: 1px solid #3d3d3d; "
        "color: #e0e0e0; selection-background-color: #404040; padding: 4px; }"
    )
    dashboard._image_selector.setToolTip(
        "Select which Docker image to use when starting the server.\n"
        "'Most Recent (auto)' automatically selects the newest image by build date."
    )
    dashboard._image_selector.currentIndexChanged.connect(
        dashboard._on_image_selection_changed
    )
    image_selector_row.addWidget(dashboard._image_selector)
    image_selector_row.addStretch()
    status_layout.addLayout(image_selector_row)

    # Populate image selector
    dashboard._populate_image_selector()

    # Separator
    separator = QFrame()
    separator.setFrameShape(QFrame.Shape.HLine)
    separator.setFrameShadow(QFrame.Shadow.Sunken)
    separator.setStyleSheet("background-color: #2d2d2d; max-height: 1px;")
    status_layout.addWidget(separator)

    # Auth Token row
    token_row = QHBoxLayout()
    token_label = QLabel("Auth Token:")
    token_label.setObjectName("statusLabel")
    token_row.addWidget(token_label)
    dashboard._server_token_field = QLineEdit()
    dashboard._server_token_field.setObjectName("tokenFieldInline")
    dashboard._server_token_field.setReadOnly(True)
    dashboard._server_token_field.setText("Not saved yet")
    dashboard._server_token_field.setFrame(False)
    dashboard._server_token_field.setStyleSheet(
        "background: transparent; border: none; font-family: monospace;"
    )
    dashboard._server_token_field.setFixedWidth(272)
    token_row.addWidget(dashboard._server_token_field)
    token_row.setSpacing(0)
    token_note = QLabel(" (for remote)")
    token_note.setObjectName("statusDateInline")
    token_note.setStyleSheet("margin-left: 0px;")
    token_row.addWidget(token_note)
    token_row.addStretch()
    status_layout.addLayout(token_row)

    layout.addWidget(status_frame, alignment=Qt.AlignmentFlag.AlignCenter)

    layout.addSpacing(20)

    # Primary control buttons
    btn_container = QWidget()
    btn_layout = QHBoxLayout(btn_container)
    btn_layout.setSpacing(12)

    dashboard._start_local_btn = QPushButton("Start Local")
    dashboard._start_local_btn.setObjectName("primaryButton")
    dashboard._start_local_btn.clicked.connect(dashboard._on_start_server_local)
    btn_layout.addWidget(dashboard._start_local_btn)

    dashboard._start_remote_btn = QPushButton("Start Remote")
    dashboard._start_remote_btn.setObjectName("primaryButton")
    dashboard._start_remote_btn.clicked.connect(dashboard._on_start_server_remote)
    btn_layout.addWidget(dashboard._start_remote_btn)

    dashboard._stop_server_btn = QPushButton("Stop")
    dashboard._stop_server_btn.setObjectName("stopButton")
    dashboard._stop_server_btn.clicked.connect(dashboard._on_stop_server)
    btn_layout.addWidget(dashboard._stop_server_btn)

    layout.addWidget(btn_container, alignment=Qt.AlignmentFlag.AlignCenter)

    layout.addSpacing(20)

    # Management section header
    mgmt_header = QLabel("Management")
    mgmt_header.setObjectName("sectionHeader")
    mgmt_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(mgmt_header)

    layout.addSpacing(10)

    # 3-column management layout
    mgmt_container = QWidget()
    mgmt_grid = QHBoxLayout(mgmt_container)
    mgmt_grid.setSpacing(26)
    mgmt_grid.addStretch()

    # Column 1: Container Management
    container_col = QFrame()
    container_col.setObjectName("managementGroup")
    container_col_layout = QVBoxLayout(container_col)
    container_col_layout.setSpacing(8)
    container_col_layout.setContentsMargins(12, 12, 12, 12)

    container_col_header = QLabel("Container")
    container_col_header.setObjectName("columnHeader")
    container_col_header.setAlignment(
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
    )
    container_col_layout.addWidget(container_col_header)

    dashboard._remove_container_btn = QPushButton("Remove")
    dashboard._remove_container_btn.setObjectName("dangerButton")
    dashboard._remove_container_btn.setMinimumWidth(140)
    dashboard._remove_container_btn.setToolTip("Remove the Docker container")
    dashboard._remove_container_btn.clicked.connect(dashboard._on_remove_container)
    container_col_layout.addWidget(dashboard._remove_container_btn)

    # Add stretch to push button up and fill remaining space
    container_col_layout.addStretch()

    mgmt_grid.addWidget(container_col)

    # Column 2: Image Management
    image_col = QFrame()
    image_col.setObjectName("managementGroup")
    image_col_layout = QVBoxLayout(image_col)
    image_col_layout.setSpacing(8)
    image_col_layout.setContentsMargins(12, 12, 12, 12)

    image_col_header = QLabel("Image")
    image_col_header.setObjectName("columnHeader")
    image_col_header.setAlignment(
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
    )
    image_col_layout.addWidget(image_col_header)

    dashboard._remove_image_btn = QPushButton("Remove")
    dashboard._remove_image_btn.setObjectName("dangerButton")
    dashboard._remove_image_btn.setMinimumWidth(140)
    dashboard._remove_image_btn.clicked.connect(dashboard._on_remove_image)
    image_col_layout.addWidget(dashboard._remove_image_btn)

    dashboard._pull_image_btn = QPushButton("Fetch Fresh")
    dashboard._pull_image_btn.setObjectName("primaryButton")
    dashboard._pull_image_btn.setMinimumWidth(140)
    dashboard._pull_image_btn.clicked.connect(dashboard._on_pull_fresh_image)
    image_col_layout.addWidget(dashboard._pull_image_btn)

    dashboard._pull_cancel_btn = QPushButton("Cancel Pull")
    dashboard._pull_cancel_btn.setObjectName("dangerButton")
    dashboard._pull_cancel_btn.setMinimumWidth(140)
    dashboard._pull_cancel_btn.clicked.connect(dashboard._on_cancel_pull)
    dashboard._pull_cancel_btn.setVisible(False)
    image_col_layout.addWidget(dashboard._pull_cancel_btn)

    mgmt_grid.addWidget(image_col)

    # Column 3: Volumes Management
    volumes_col = QFrame()
    volumes_col.setObjectName("managementGroup")
    volumes_col_layout = QVBoxLayout(volumes_col)
    volumes_col_layout.setSpacing(8)
    volumes_col_layout.setContentsMargins(12, 12, 12, 12)

    volumes_col_header = QLabel("Volumes")
    volumes_col_header.setObjectName("columnHeader")
    volumes_col_header.setAlignment(
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
    )
    volumes_col_layout.addWidget(volumes_col_header)

    dashboard._remove_data_volume_btn = QPushButton("Remove Data")
    dashboard._remove_data_volume_btn.setObjectName("dangerButton")
    dashboard._remove_data_volume_btn.setMinimumWidth(140)
    dashboard._remove_data_volume_btn.clicked.connect(dashboard._on_remove_data_volume)
    volumes_col_layout.addWidget(dashboard._remove_data_volume_btn)

    dashboard._remove_models_volume_btn = QPushButton("Remove Models")
    dashboard._remove_models_volume_btn.setObjectName("dangerButton")
    dashboard._remove_models_volume_btn.setMinimumWidth(140)
    dashboard._remove_models_volume_btn.clicked.connect(
        dashboard._on_remove_models_volume
    )
    volumes_col_layout.addWidget(dashboard._remove_models_volume_btn)

    dashboard._reset_runtime_volume_btn = QPushButton("Reset Runtime Deps")
    dashboard._reset_runtime_volume_btn.setObjectName("secondaryButton")
    dashboard._reset_runtime_volume_btn.setMinimumWidth(140)
    dashboard._reset_runtime_volume_btn.clicked.connect(
        dashboard._on_reset_runtime_dependencies
    )
    volumes_col_layout.addWidget(dashboard._reset_runtime_volume_btn)

    mgmt_grid.addWidget(volumes_col)
    mgmt_grid.addStretch()

    layout.addWidget(mgmt_container, alignment=Qt.AlignmentFlag.AlignCenter)

    layout.addSpacing(12)

    # Model selector panel (under management boxes)
    models_frame = QFrame()
    models_frame.setObjectName("statusCard")
    models_frame.setFixedWidth(card_width)
    models_layout = QVBoxLayout(models_frame)
    models_layout.setSpacing(10)
    models_layout.setContentsMargins(16, 0, 16, 12)

    models_title = QLabel("Transcription Models")
    models_title.setObjectName("sectionHeader")
    models_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    models_layout.addWidget(models_title)

    combo_style = (
        "QComboBox { background-color: #2d2d2d; border: 1px solid #3d3d3d; "
        "border-radius: 6px; padding: 6px 10px; color: #e0e0e0; font-size: 12px; }"
        "QComboBox:hover { border-color: #505050; }"
        "QComboBox::drop-down { border: none; width: 20px; }"
        "QComboBox::down-arrow { image: none; border-left: 4px solid transparent; "
        "border-right: 4px solid transparent; border-top: 5px solid #808080; margin-right: 6px; }"
        "QComboBox QAbstractItemView { background-color: #2d2d2d; border: 1px solid #3d3d3d; "
        "color: #e0e0e0; selection-background-color: #404040; padding: 4px; }"
    )
    custom_style = (
        "QLineEdit { background-color: #2d2d2d; border: 1px solid #3d3d3d; "
        "border-radius: 6px; padding: 6px 10px; color: #e0e0e0; font-size: 12px; }"
    )

    models_grid = QGridLayout()
    models_grid.setHorizontalSpacing(10)
    models_grid.setVerticalSpacing(10)

    # Main transcriber model row
    main_label = QLabel("Main Transcriber Model:")
    main_label.setObjectName("statusLabel")
    models_grid.addWidget(main_label, 0, 0)

    dashboard._main_model_combo = QComboBox()
    dashboard._main_model_combo.setMinimumWidth(280)
    dashboard._main_model_combo.setStyleSheet(combo_style)
    dashboard._main_model_combo.currentIndexChanged.connect(
        dashboard._on_main_model_selection_changed
    )
    models_grid.addWidget(dashboard._main_model_combo, 0, 1)

    dashboard._main_model_custom = QLineEdit()
    dashboard._main_model_custom.setPlaceholderText("Custom model id...")
    dashboard._main_model_custom.setStyleSheet(custom_style)
    dashboard._main_model_custom.setVisible(False)
    dashboard._main_model_custom.editingFinished.connect(
        dashboard._on_main_model_custom_changed
    )
    models_layout.addWidget(dashboard._main_model_custom)

    # Live Mode model row
    live_label = QLabel("Live Mode Model:")
    live_label.setObjectName("statusLabel")
    models_grid.addWidget(live_label, 1, 0)

    dashboard._live_model_combo = QComboBox()
    dashboard._live_model_combo.setMinimumWidth(280)
    dashboard._live_model_combo.setStyleSheet(combo_style)
    dashboard._live_model_combo.currentIndexChanged.connect(
        dashboard._on_live_model_selection_changed
    )
    models_grid.addWidget(dashboard._live_model_combo, 1, 1)
    models_grid.addItem(
        QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum),
        0,
        2,
        2,
        1,
    )
    models_layout.addLayout(models_grid)

    dashboard._live_model_custom = QLineEdit()
    dashboard._live_model_custom.setPlaceholderText("Custom model id...")
    dashboard._live_model_custom.setStyleSheet(custom_style)
    dashboard._live_model_custom.setVisible(False)
    dashboard._live_model_custom.editingFinished.connect(
        dashboard._on_live_model_custom_changed
    )
    models_layout.addWidget(dashboard._live_model_custom)

    # Populate model selectors from config
    dashboard._init_model_selectors()

    layout.addWidget(models_frame, alignment=Qt.AlignmentFlag.AlignCenter)

    layout.addSpacing(20)

    # Volumes status panel
    volumes_frame = QFrame()
    volumes_frame.setObjectName("volumesStatusCard")
    volumes_frame.setFixedWidth(card_width)
    volumes_layout = QVBoxLayout(volumes_frame)
    volumes_layout.setSpacing(10)
    volumes_layout.setContentsMargins(16, 12, 16, 12)

    volumes_title = QLabel("Volumes")
    volumes_title.setObjectName("sectionHeader")
    volumes_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    volumes_layout.addWidget(volumes_title)

    # Data volume row
    data_volume_row = QHBoxLayout()
    data_volume_label = QLabel("Data Volume:")
    data_volume_label.setObjectName("statusLabel")
    data_volume_label.setMinimumWidth(110)
    data_volume_row.addWidget(data_volume_label)

    dashboard._data_volume_status = QLabel("Not found")
    dashboard._data_volume_status.setObjectName("statusValue")
    data_volume_row.addWidget(dashboard._data_volume_status)

    dashboard._data_volume_size = QLabel("")
    dashboard._data_volume_size.setObjectName("statusDateInline")
    data_volume_row.addWidget(dashboard._data_volume_size)

    data_volume_row.addStretch()
    volumes_layout.addLayout(data_volume_row)

    # Models volume row
    models_volume_row = QHBoxLayout()
    models_volume_label = QLabel("Models Volume:")
    models_volume_label.setObjectName("statusLabel")
    models_volume_label.setMinimumWidth(110)
    models_volume_row.addWidget(models_volume_label)

    dashboard._models_volume_status = QLabel("Not found")
    dashboard._models_volume_status.setObjectName("statusValue")
    models_volume_row.addWidget(dashboard._models_volume_status)

    dashboard._models_volume_size = QLabel("")
    dashboard._models_volume_size.setObjectName("statusDateInline")
    models_volume_row.addWidget(dashboard._models_volume_size)

    models_volume_row.addStretch()
    volumes_layout.addLayout(models_volume_row)

    # Runtime dependency volume row
    runtime_volume_row = QHBoxLayout()
    runtime_volume_label = QLabel("Runtime Volume:")
    runtime_volume_label.setObjectName("statusLabel")
    runtime_volume_label.setMinimumWidth(110)
    runtime_volume_row.addWidget(runtime_volume_label)

    dashboard._runtime_volume_status = QLabel("Not found")
    dashboard._runtime_volume_status.setObjectName("statusValue")
    runtime_volume_row.addWidget(dashboard._runtime_volume_status)

    dashboard._runtime_volume_size = QLabel("")
    dashboard._runtime_volume_size.setObjectName("statusDateInline")
    runtime_volume_row.addWidget(dashboard._runtime_volume_size)

    runtime_volume_row.addStretch()
    volumes_layout.addLayout(runtime_volume_row)

    # Runtime package cache volume row
    uv_cache_volume_row = QHBoxLayout()
    uv_cache_volume_label = QLabel("UV Cache Volume:")
    uv_cache_volume_label.setObjectName("statusLabel")
    uv_cache_volume_label.setMinimumWidth(110)
    uv_cache_volume_row.addWidget(uv_cache_volume_label)

    dashboard._uv_cache_volume_status = QLabel("Not found")
    dashboard._uv_cache_volume_status.setObjectName("statusValue")
    uv_cache_volume_row.addWidget(dashboard._uv_cache_volume_status)

    dashboard._uv_cache_volume_size = QLabel("")
    dashboard._uv_cache_volume_size.setObjectName("statusDateInline")
    uv_cache_volume_row.addWidget(dashboard._uv_cache_volume_size)

    uv_cache_volume_row.addStretch()
    volumes_layout.addLayout(uv_cache_volume_row)

    # Models list
    dashboard._models_list_label = QLabel("")
    dashboard._models_list_label.setObjectName("modelsListLabel")
    dashboard._models_list_label.setWordWrap(True)
    dashboard._models_list_label.setStyleSheet(
        "color: #a0a0a0; font-size: 11px; margin-left: 110px;"
    )
    dashboard._models_list_label.setVisible(False)
    volumes_layout.addWidget(dashboard._models_list_label)

    # Volume path info
    volumes_path = dashboard._docker_manager.get_volumes_base_path()
    path_label = QLabel(f"Path: {volumes_path}")
    path_label.setObjectName("volumePathLabel")
    path_label.setStyleSheet("color: #6c757d; font-size: 10px; margin-top: 4px;")
    volumes_layout.addWidget(path_label)

    layout.addWidget(volumes_frame, alignment=Qt.AlignmentFlag.AlignCenter)

    layout.addSpacing(15)

    # Show logs button
    dashboard._show_server_logs_btn = QPushButton("Show Logs")
    dashboard._show_server_logs_btn.setObjectName("secondaryButton")
    logs_icon = dashboard._icon_loader.get_icon("logs")
    if not logs_icon.isNull():
        dashboard._show_server_logs_btn.setIcon(logs_icon)
    dashboard._show_server_logs_btn.clicked.connect(dashboard._toggle_server_logs)
    layout.addWidget(
        dashboard._show_server_logs_btn, alignment=Qt.AlignmentFlag.AlignCenter
    )

    layout.addStretch()

    scroll.setWidget(view)
    return scroll
