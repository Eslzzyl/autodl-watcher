import hashlib
import requests
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
)


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.token = None
        self.setWindowTitle("用户登录")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        # 手机号输入
        phone_layout = QHBoxLayout()
        phone_layout.addWidget(QLabel("账号:"))
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("请输入手机号")
        phone_layout.addWidget(self.phone_input)
        layout.addLayout(phone_layout)
        # 密码输入
        pwd_layout = QHBoxLayout()
        pwd_layout.addWidget(QLabel("密码:"))
        self.pwd_input = QLineEdit()
        self.pwd_input.setPlaceholderText("请输入密码")
        self.pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_layout.addWidget(self.pwd_input)
        layout.addLayout(pwd_layout)
        # 按钮区域
        btn_layout = QHBoxLayout()
        self.login_btn = QPushButton("登录")
        self.login_btn.clicked.connect(self.on_login)
        btn_layout.addWidget(self.login_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def on_login(self):
        phone = self.phone_input.text().strip()
        pwd = self.pwd_input.text().strip()
        if not phone or not pwd:
            QMessageBox.warning(self, "输入错误", "请输入账号和密码")
            return

        # 使用 SHA1 对密码进行散列
        hashed_pwd = hashlib.sha1(pwd.encode()).hexdigest()

        # 第一个请求: 获取 ticket
        login_payload = {
            "phone": phone,
            "password": hashed_pwd,
            "v_code": "",
            "phone_area": "+86",
            "picture_id": None,
        }
        try:
            resp = requests.post(
                "https://www.autodl.com/api/v1/new_login", json=login_payload
            )
            resp_data = resp.json()
            if resp_data.get("code") != "Success":
                QMessageBox.critical(self, "登录失败", resp_data.get("msg", "未知错误"))
                return
            ticket = resp_data["data"]["ticket"]
        except Exception as e:
            QMessageBox.critical(self, "请求错误", str(e))
            return

        # 第二个请求: 使用 ticket 获取 token
        # 注意此处私有云和公有云使用不同的接口
        passport_payload = {"ticket": ticket, "third_party_login": False}
        try:
            resp2 = requests.post(
                "https://private.autodl.com/api/v2/login", json=passport_payload
            )
            resp2_data = resp2.json()
            if resp2_data.get("code") != "Success":
                QMessageBox.critical(
                    self, "登录失败", resp2_data.get("msg", "未知错误")
                )
                return
            self.token = resp2_data["data"]["token"]
            QMessageBox.information(self, "登录成功", "账号登录成功")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "请求错误", str(e))
            return

    def get_token(self) -> str:
        return self.token
