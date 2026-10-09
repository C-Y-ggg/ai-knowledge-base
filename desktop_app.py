import sys
import os
import httpx
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,QFileDialog, QMessageBox)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RAG 智能问答桌面助手")
        self.resize(1000, 750)

        current_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(current_dir, "slm.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 1. 核心：嵌入浏览器引擎，加载你的聊天界面
        self.web_view = QWebEngineView()
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(current_dir, "test_stream.html")
        self.web_view.load(QUrl.fromLocalFile(html_path))
        self.setCentralWidget(self.web_view)

        # 2. 创建顶部菜单栏
        self.create_menu_bar()

    def create_menu_bar(self):
        menu_bar = self.menuBar()

        # 【文件】菜单
        file_menu = menu_bar.addMenu("文件")

        # 【上传文档】动作
        upload_action = QAction("📄 上传新文档", self)
        upload_action.triggered.connect(self.upload_file)
        file_menu.addAction(upload_action)

        file_menu.addSeparator()  # 加一条分割线

        # 【退出】动作
        exit_action = QAction("退出应用", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def upload_file(self):
        """打开系统原生文件选择器，上传文件到 FastAPI"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择要上传的文档",
            "",
            "文档文件 (*.pdf *.txt *.docx *.md);;所有文件 (*.*)"
        )

        if not file_path:
            return  # 用户取消了选择

        file_name = os.path.basename(file_path)

        # 弹窗提示用户正在上传（因为网络请求可能会稍微卡顿一下UI）
        QMessageBox.information(self, "上传中", f"正在上传《{file_name}》，请稍候...\n\n后台将自动进行解析和向量化。")

        # 发送 HTTP 请求到你的 FastAPI 后端
        try:
            url = "http://127.0.0.1:8000/api/v1/knowledge-bases/1/knowledge/file"
            with open(file_path, "rb") as f:
                files = {"file": (file_name, f, "application/octet-stream")}
                response = httpx.post(url, files=files, timeout=30.0)

            if response.status_code == 202:
                QMessageBox.information(
                    self, "上传成功",
                    f"《{file_name}》已成功加入处理队列！\n\n后台 Worker 正在解析中，稍等几秒后即可在聊天框提问。"
                )
            else:
                QMessageBox.warning(self, "上传失败", f"服务器返回错误：{response.status_code}\n{response.text}")

        except Exception as e:
            QMessageBox.critical(self, "网络错误", f"无法连接到后端服务，请确保 uvicorn 正在运行。\n\n详细错误：{e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(current_dir, "slm.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())