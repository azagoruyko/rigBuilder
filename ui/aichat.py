import ollama
from ..qt import *
from ..ai import engine
from ..settings import settings

SYSTEM_PROMPT = """
You are an AI assistant integrated into Rig Builder, a standalone modular tool development environment.
Rig Builder is a general-purpose platform for creating, managing, and executing Python modules to build automation tools for any host.

Key features of Rig Builder:
- Modular architecture: Tools are built from reusable components called 'modules'.
- Modules are independant, flat, made out of a single file.
- Host Agnostic Integration: Can connect to various hosts (like Maya, Unreal, Blender, Houdini, etc.) or run in Standalone mode.
- Attribute System: Modules have exposed attributes for configuration and interactivity.
- Interactive Execution: Modules can be executed in real-time within the host context.

When helping users:
- Provide compact, modular Python code compatible with the Rig Builder environment and appropriate host.
- Avoid long descriptions, verbose explanations, or excessive comments in the code.
- DO NOT include `if __name__ == "__main__":` blocks or standalone execution boilerplate; the code is intended to run within Rig Builder.
- Focus on direct solutions and general tool-building best practices.
- If the user asks about the environment, explain that they are inside Rig Builder.

Example of Rig Builder code:
```python
# @ is shortcut for 'attr_' prefix. 
# Don't create attributes yourself! 
# Attributes store JSON-compatible data only!
print("lineAttr:", @lineAttr, type(@lineAttr))

# Progress bar functions
beginProgress("Some slow operation", 10)
for i in range(10):
    stepProgress(i)
    time.sleep(0.1)
endProgress()

warning("Warn user in case of something important")
error("Report error to user")
exit() # exit current module execution
```
"""

class AIChatWorker(QThread):
    chunkReceived = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, messages, temperature=0.7):
        super().__init__()
        self.messages = messages
        self.temperature = temperature
        self._isRunning = True

    def run(self):
        try:
            # Add system prompt for context and language
            fullMessages = [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'system', 'content': f'Translate all textual output to {settings.aiLanguage}. Do not translate code!'}
            ] + self.messages

            for chunk in ollama.chat(
                model=settings.ollamaModel,
                messages=fullMessages,
                stream=True,
                options={'temperature': self.temperature}
            ):
                if not self._isRunning:
                    break
                
                content = chunk.get('message', {}).get('content', '') if isinstance(chunk, dict) else getattr(chunk.message, 'content', '')
                if content:
                    self.chunkReceived.emit(content)
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._isRunning = False


class AIChatDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Chat")
        self.resize(600, 700)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self.messages = []
        self.currentResponse = ""
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Chat history
        self.history = QTextBrowser()
        self.history.setOpenExternalLinks(True)
        self.history.setReadOnly(True)
        self.history.setPlaceholderText("Chat history will appear here...")
        # PySide6 supports markdown
        self.history.setAcceptRichText(True)
        layout.addWidget(self.history)

        # Input area
        inputLayout = QHBoxLayout()
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Type your message here (Ctrl+Enter to send)...")
        self.input.setFixedHeight(80)
        
        # Shortcut for sending
        sendAction = QAction(self)
        sendAction.setShortcut("Ctrl+Return")
        sendAction.triggered.connect(self.sendMessage)
        self.addAction(sendAction)
        
        sendAction2 = QAction(self)
        sendAction2.setShortcut("Ctrl+Enter")
        sendAction2.triggered.connect(self.sendMessage)
        self.addAction(sendAction2)

        self.sendBtn = QPushButton("⏎ Send")
        self.sendBtn.clicked.connect(self.sendMessage)

        self.clearBtn = QPushButton("🗑 Clear")
        self.clearBtn.clicked.connect(self.clearChat)

        inputLayout.addWidget(self.input)
        
        btnLayout = QVBoxLayout()
        btnLayout.addWidget(self.sendBtn)
        btnLayout.addWidget(self.clearBtn)
        inputLayout.addLayout(btnLayout)
        
        layout.addLayout(inputLayout)

        self.statusLabel = QLabel("Ready")
        self.statusLabel.setStyleSheet("color: #7a8699; font-style: italic;")
        layout.addWidget(self.statusLabel)

        self.input.setFocus()

    def sendMessage(self):
        text = self.input.toPlainText().strip()
        if not text or self.worker:
            return

        self.input.clear()
        self.messages.append({'role': 'user', 'content': text})
        self.updateHistory()

        self.worker = AIChatWorker(self.messages)
        self.worker.chunkReceived.connect(self.onChunkReceived)
        self.worker.finished.connect(self.onFinished)
        self.worker.error.connect(self.onError)
        
        self.currentResponse = ""
        self.statusLabel.setText("Thinking...")
        self.sendBtn.setEnabled(False)
        self.worker.start()

    def clearChat(self):
        if self.worker or not self.messages:
            return
            
        if QMessageBox.question(self, "AI Chat", "Clear conversation history?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.messages = []
            self.currentResponse = ""
            self.history.clear()
            self.statusLabel.setText("Chat cleared")

    def onChunkReceived(self, chunk):
        if not self.worker:
            return
        self.currentResponse += chunk
        self.updateHistory(streaming=True)

    def onFinished(self):
        if not self.worker:
            return
        self.messages.append({'role': 'assistant', 'content': self.currentResponse})
        self.worker = None
        self.currentResponse = ""
        self.statusLabel.setText("Ready")
        self.sendBtn.setEnabled(True)
        self.updateHistory()

    def onError(self, error):
        self.statusLabel.setText(f"Error: {error}")
        self.worker = None
        self.sendBtn.setEnabled(True)

    def updateHistory(self, streaming=False):
        fullMd = ""
        
        def formatContent(content):
            # Format thinking process if present
            if "<think>" in content:
                if "</think>" in content:
                    content = content.replace("<think>", "\n\n> **Thinking:**\n> ")
                    content = content.replace("</think>", "\n\n---\n\n")
                else:
                    # Still thinking
                    content = content.replace("<think>", "\n\n> **Thinking:**\n> ")
                    content += "\n> ..."
            return content

        for msg in self.messages:
            role = msg['role'].capitalize()
            content = formatContent(msg['content'])
            
            if msg['role'] == 'user':
                fullMd += f"### 👤 {role}\n{content}\n\n"
            else:
                fullMd += f"### 🤖 {role}\n{content}\n\n"

        if streaming:
            content = formatContent(self.currentResponse)
            fullMd += f"### 🤖 Assistant\n{content}\n\n"

        self.history.setMarkdown(fullMd)
        # Scroll to bottom
        self.history.verticalScrollBar().setValue(self.history.verticalScrollBar().maximum())

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        super().closeEvent(event)
