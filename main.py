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
)
from PySide6.QtCore import QTimer, QThread, Signal, QUrl, QEventLoop, Qt
from PySide6.QtGui import QColor
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from win11toast import toast
import threading
from login import LoginDialog


class RequestThread(QThread):
    finished = Signal(dict)

    def __init__(self, url, token):
        super().__init__()
        self.url = url
        self.token = token

    def run(self):
        manager = QNetworkAccessManager()
        request = QNetworkRequest(QUrl(self.url))
        request.setRawHeader(b"Authorization", self.token.encode())
        request.setHeader(
            QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json"
        )

        reply = manager.post(request, b'{"page_index": 1, "page_size": 10}')

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
        self.setGeometry(200, 100, 600, 400)

        # 初始化变量
        self.token = ""
        self.monitored_machines = set()
        self.current_machines = {}
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_status)

        # 初始化UI
        self.init_ui()
        # 加载本地存储的 token
        self.token = self.load_token()
        if self.token:
            self.token_input.setPlainText(self.token)
            self.fetch_machines()  # token存在立即刷新机器列表

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

        self.thread = RequestThread(
            "https://private.autodl.com/api/v2/machine/list", self.token
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

        self.thread = RequestThread(
            "https://private.autodl.com/api/v2/machine/list", self.token
        )
        self.thread.finished.connect(self.handle_status_update)
        self.thread.start()

    def handle_status_update(self, result):
        if "error" in result or result.get("code") != "Success":
            return

        # 从下拉菜单获取监控阈值
        threshold = int(self.threshold_combo.currentText())
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
                threading.Thread(
                    target=toast,
                    args=(message, "立即前往"),
                    kwargs={"on_click": "https://private.autodl.com/console/machine"},
                    daemon=True,
                ).start()

        self.update_machine_list(result)

    def open_login_dialog(self):
        dialog = LoginDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            token = dialog.get_token()
            if token:
                self.token_input.setPlainText(token)
                self.token = token
                self.save_token(token)
                self.fetch_machines()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
