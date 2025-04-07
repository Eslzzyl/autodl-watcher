import sys
import json
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSpinBox,
    QCheckBox,
    QMessageBox,
    QPlainTextEdit,
    QComboBox,
    QAbstractItemView,
    QDialog,
    QButtonGroup
)
from PySide6.QtCore import QTimer, QThread, Signal, QUrl, QEventLoop, Qt
from PySide6.QtGui import QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from win11toast import toast
import threading
from login import LoginDialog


class RequestThread(QThread):
    finished = Signal(dict)

    def __init__(self, url, token, payload=None):
        super().__init__()
        self.url = url
        self.token = token
        self.payload = payload or {"page_index": 1, "page_size": 4}

    def run(self):
        manager = QNetworkAccessManager()
        request = QNetworkRequest(QUrl(self.url))
        request.setRawHeader(b"Authorization", self.token.encode())
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json"
        )
        data_bytes = json.dumps(self.payload).encode()
        reply = manager.post(request, data_bytes)

        loop = QEventLoop()
        reply.finished.connect(loop.quit)
        loop.exec()

        if reply.error() == QNetworkReply.NetworkError.NoError:
            data = json.loads(reply.readAll().data().decode("utf-8"))
            self.finished.emit(data)
        else:
            self.finished.emit({"error": reply.errorString()})


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoDL Watcher")
        self.setGeometry(200, 100, 600, 600)

        # 初始化变量
        self.token = ""
        self.monitored_machines = set()
        self.current_machines = {}
        self.current_page = 1
        self.page_size = 4
        # 新增实例分页参数（固定）
        self.instance_page_index = 1
        self.instance_page_size = 10
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_status)
        # 添加实例单选组（自动开机专用）
        self.instance_radio_group = None

        # 初始化UI
        self.init_ui()
        # 加载本地存储的 token
        self.token = self.load_token()
        if self.token:
            self.token_input.setPlainText(self.token)
            self.fetch_machines()  # token存在立即刷新机器列表
            self.fetch_instances()  # 加载实例列表

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Token输入区域
        token_layout = QHBoxLayout()
        token_layout.addWidget(QLabel("Authorization Token:"))
        # 修改为多行输入
        self.token_input = QPlainTextEdit()
        self.token_input.setPlaceholderText("输入你的token")
        self.token_input.setFixedHeight(160)
        token_layout.addWidget(self.token_input)
        # 新增登录按钮
        self.login_btn = QPushButton("登录账号")
        self.login_btn.clicked.connect(self.open_login_dialog)
        self.refresh_btn = QPushButton("刷新机器列表")
        self.refresh_btn.clicked.connect(self.fetch_machines)
        btn_layout = QVBoxLayout()
        btn_layout.addWidget(self.login_btn)
        btn_layout.addWidget(self.refresh_btn)
        token_layout.addLayout(btn_layout)
        layout.addLayout(token_layout)

        # 监控设置区域
        monitor_layout = QHBoxLayout()
        monitor_layout.addWidget(QLabel("检查间隔:"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 60)
        self.interval_spin.setValue(5)
        monitor_layout.addWidget(self.interval_spin)
        # 添加单位选择，分钟或秒
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["分钟", "秒"])
        monitor_layout.addWidget(self.unit_combo)
        # 修改监控阈值为下拉菜单1~8
        monitor_layout.addWidget(QLabel("监控阈值:"))
        self.threshold_combo = QComboBox()
        self.threshold_combo.addItems([str(i) for i in range(1, 9)])
        monitor_layout.addWidget(self.threshold_combo)
        self.start_btn = QPushButton("开始监控")
        self.start_btn.clicked.connect(self.toggle_monitoring)
        monitor_layout.addWidget(self.start_btn)
        layout.addLayout(monitor_layout)

        # 机器列表表格
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["监控", "机器ID", "机器名称", "GPU型号", "总GPU", "空闲GPU", "状态"]
        )
        # 设置表格禁止编辑
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # 允许用户手动调整列宽（初始自动调整后切换为Interactive）
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        layout.addWidget(self.table)

        # 新增分页区域
        pagination_layout = QHBoxLayout()
        self.prev_button = QPushButton("上一页")
        self.prev_button.clicked.connect(self.prev_page)
        pagination_layout.addWidget(self.prev_button)
        self.page_label = QLabel("第 1 页")
        pagination_layout.addWidget(self.page_label)
        self.next_button = QPushButton("下一页")
        self.next_button.clicked.connect(self.next_page)
        pagination_layout.addWidget(self.next_button)
        layout.addLayout(pagination_layout)

        # 新增实例列表区域（在机器分页下方）
        layout.addWidget(QLabel("实例列表"))
        self.instance_table = QTableWidget()
        self.instance_table.setColumnCount(5)
        self.instance_table.setHorizontalHeaderLabels(
            ["自动开机", "实例ID", "实例别名", "所在机器", "状态"]
        )
        self.instance_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.instance_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.instance_table.setMinimumHeight(200)
        layout.addWidget(self.instance_table)
        # 新增实例分页区域
        instance_pagination_layout = QHBoxLayout()
        self.instance_prev_button = QPushButton("上一页")
        self.instance_prev_button.clicked.connect(self.instance_prev_page)
        instance_pagination_layout.addWidget(self.instance_prev_button)
        self.instance_page_label = QLabel("第 1 页")
        instance_pagination_layout.addWidget(self.instance_page_label)
        self.instance_next_button = QPushButton("下一页")
        self.instance_next_button.clicked.connect(self.instance_next_page)
        instance_pagination_layout.addWidget(self.instance_next_button)
        layout.addLayout(instance_pagination_layout)
        # 新增：创建单选按钮组（全局只允许选择一个）
        from PySide6.QtWidgets import QButtonGroup
        self.instance_radio_group = QButtonGroup(self)
        self.instance_radio_group.setExclusive(True)

    def load_token(self):
        try:
            with open("token.txt", "r") as f:
                return f.read().strip()
        except Exception:
            return ""

    def save_token(self, token):
        try:
            with open("token.txt", "w") as f:
                f.write(token)
        except Exception:
            pass

    def fetch_machines(self):
        self.token = self.token_input.toPlainText().strip()
        if not self.token:
            QMessageBox.warning(self, "错误", "请输入有效的 Token")
            return
        # 保存 token 到本地
        self.save_token(self.token)
        payload = {"page_index": self.current_page, "page_size": self.page_size}
        self.thread = RequestThread(
            "https://private.autodl.com/api/v2/machine/list", self.token, payload
        )
        self.thread.finished.connect(self.update_machine_list)
        self.thread.start()

    def update_machine_list(self, result):
        if "error" in result:
            QMessageBox.critical(self, "错误", f"请求失败: {result['error']}")
            return

        if result.get("code") != "Success":
            QMessageBox.warning(
                self, "警告", f"API返回错误: {result.get('msg', '未知错误')}"
            )
            return

        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.current_machines.clear()

        for machine in result["data"]["list"]:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # 监控复选框
            machine_id = machine["machine_id"]
            cb = QCheckBox()
            cb.setChecked(machine_id in self.monitored_machines)
            # 连接复选框状态变化信号
            cb.stateChanged.connect(
                lambda state, m_id=machine_id: self.update_monitored_machines(
                    m_id, state
                )
            )
            self.table.setCellWidget(row, 0, cb)

            # 设置各项并居中显示
            item_id = QTableWidgetItem(machine_id)
            item_id.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, item_id)

            item_name = QTableWidgetItem(machine["machine_name"])
            item_name.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, item_name)

            item_gpu = QTableWidgetItem(machine["gpu_name"])
            item_gpu.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 3, item_gpu)

            item_total = QTableWidgetItem(str(machine["gpu"]["total"]))
            item_total.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, item_total)

            item_idle = QTableWidgetItem(str(machine["gpu"]["idle"]))
            item_idle.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, item_idle)

            status = self.get_status_text(machine)
            item_status = QTableWidgetItem(status)
            item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_status.setForeground(self.get_status_color(machine))
            self.table.setItem(row, 6, item_status)

            self.current_machines[machine_id] = machine

        self.table.blockSignals(False)
        # 根据内容自动调整列宽，然后允许用户手动更改
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )

        # 更新分页按钮状态
        self.page_label.setText(f"第 {self.current_page} 页")
        self.prev_button.setEnabled(self.current_page > 1)
        if len(result["data"]["list"]) < self.page_size:
            self.next_button.setEnabled(False)
        else:
            self.next_button.setEnabled(True)

    def update_monitored_machines(self, machine_id, state):
        """根据复选框状态更新监控列表"""
        if state == Qt.CheckState.Checked.value:
            self.monitored_machines.add(machine_id)
        else:
            self.monitored_machines.discard(machine_id)

    def get_status_text(self, machine):
        if machine["health_status"] != 0:
            return "异常"
        if machine["online_status"] != 2:
            return "离线"
        return "有空闲卡" if machine["gpu"]["idle"] > 0 else "全满"

    def get_status_color(self, machine):
        if machine["health_status"] != 0 or machine["online_status"] != 2:
            return QColor(255, 0, 0)
        return QColor(0, 200, 0) if machine["gpu"]["idle"] > 0 else QColor(255, 165, 0)

    def toggle_monitoring(self):
        if self.timer.isActive():
            self.timer.stop()
            self.start_btn.setText("开始监控")
        else:
            # 根据单位转换间隔：分钟 -> 毫秒, 秒 -> 毫秒
            value = self.interval_spin.value()
            unit = self.unit_combo.currentText()
            if unit == "分钟":
                interval = value * 60 * 1000
            else:  # 秒
                interval = value * 1000
            self.timer.start(interval)
            self.start_btn.setText("停止监控")
            self.check_status()  # 立即执行一次检查

    def check_status(self):
        if not self.token:
            return
        payload = {"page_index": self.current_page, "page_size": self.page_size}
        self.thread = RequestThread(
            "https://private.autodl.com/api/v2/machine/list", self.token, payload
        )
        self.thread.finished.connect(self.handle_status_update)
        self.thread.start()

    def handle_status_update(self, result):
        if "error" in result or result.get("code") != "Success":
            return

        # 从下拉菜单获取监控阈值
        threshold = int(self.threshold_combo.currentText())
        # 获取用户在实例列表中选择自动开机的实例（如果有）
        selected_instance = None
        for rb in self.instance_radio_group.buttons():
            if rb.isChecked():
                selected_instance = rb.property("instance_uuid")
                break

        for machine in result["data"]["list"]:
            machine_id = machine["machine_id"]
            if (
                machine_id in self.monitored_machines
                and machine["gpu"]["idle"] >= threshold
            ):
                message = (
                    f"{machine['machine_name']} 有 {machine['gpu']['idle']} 个空闲GPU！"
                )
                print(message)
                if selected_instance:
                    self.power_on_instance(selected_instance)
                else:
                    threading.Thread(
                        target=toast,
                        args=(message, "立即前往"),
                        kwargs={"on_click": "https://private.autodl.com/console/machine"},
                        daemon=True,
                    ).start()

        self.update_machine_list(result)

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.fetch_machines()

    def next_page(self):
        self.current_page += 1
        self.fetch_machines()

    def fetch_instances(self):
        if not self.token:
            return
        payload = {
            "page_index": self.instance_page_index,
            "page_size": self.instance_page_size,
            "tenant_uuid": self.token,
        }
        self.instance_thread = RequestThread(
            "https://private.autodl.com/api/v2/instance/list", self.token, payload
        )
        self.instance_thread.finished.connect(self.update_instance_list)
        self.instance_thread.start()

    def update_instance_list(self, result):
        if "error" in result or result.get("code") != "Success":
            return
        self.instance_table.setRowCount(0)
        # 清空上次添加的单选按钮组
        self.instance_radio_group = QButtonGroup(self)
        self.instance_radio_group.setExclusive(True)
        
        for instance in result["data"]["list"]:
            row = self.instance_table.rowCount()
            self.instance_table.insertRow(row)
            # 新增：自动开机单选按钮在第一列
            from PySide6.QtWidgets import QRadioButton
            rb = QRadioButton()
            rb.setProperty("instance_uuid", instance["instance_uuid"])
            # 设置单选按钮水平居中
            rb.setStyleSheet("margin-left:auto; margin-right:auto;")
            # 判断状态, 状态"开机"禁用该按钮
            status = instance.get("status", "")
            display_status = (
                "关机" if status == "shutdown" else "开机" if status == "running" else status
            )
            if display_status == "开机":
                rb.setEnabled(False)
            self.instance_radio_group.addButton(rb)
            self.instance_table.setCellWidget(row, 0, rb)
            
            # 实例ID -> 第二列
            item_id = QTableWidgetItem(instance["instance_uuid"])
            item_id.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.instance_table.setItem(row, 1, item_id)
            # 实例别名 -> 第三列
            item_name = QTableWidgetItem(instance["instance_name"])
            item_name.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.instance_table.setItem(row, 2, item_name)
            # 所在机器 -> 第四列
            item_machine = QTableWidgetItem(instance["machine_name"])
            item_machine.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.instance_table.setItem(row, 3, item_machine)
            # 状态 -> 第五列
            item_status = QTableWidgetItem(display_status)
            item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if display_status == "开机":
                item_status.setForeground(QColor(0, 200, 0))
            self.instance_table.setItem(row, 4, item_status)
        
        # 更新实例分页按钮状态
        max_page = result["data"].get("max_page", 1)
        self.instance_page_label.setText(f"第 {self.instance_page_index} 页")
        self.instance_prev_button.setEnabled(self.instance_page_index > 1)
        self.instance_next_button.setEnabled(self.instance_page_index < max_page)

    def power_on_instance(self, instance_uuid):
        # 发起自动开机请求
        url = "https://private.autodl.com/api/v2/instance/power_on"
        payload = {"instance_uuid": instance_uuid, "start_mode": "gpu"}
        # 使用 RequestThread 发送 POST 请求，不关心返回结果
        thread = RequestThread(url, self.token, payload)
        thread.start()

    def instance_prev_page(self):
        if self.instance_page_index > 1:
            self.instance_page_index -= 1
            self.fetch_instances()

    def instance_next_page(self):
        self.instance_page_index += 1
        self.fetch_instances()

    def open_login_dialog(self):
        dialog = LoginDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            token = dialog.get_token()
            if token:
                self.token_input.setPlainText(token)
                self.token = token
                self.save_token(token)
                self.fetch_machines()
                self.fetch_instances()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
