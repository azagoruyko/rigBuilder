import ollama
from ..qt import *
from ..ai import engine
from ..settings import settings


class AIChatWorker(QThread):
    chunkReceived = Signal(str)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, messages, temperature=0.7):
        super().__init__()
        self.messages = messages
        self.temperature = temperature
        self._isRunning = True

    def run(self):
        try:
            # Add system prompt for context and language
            fullMessages = engine.getChatMessages(self.messages)

            lastChunk = None
            for chunk in ollama.chat(
                model=settings.ollamaModel,
                messages=fullMessages,
                stream=True,
                options={'temperature': self.temperature}
            ):
                if not self._isRunning:
                    break
                
                lastChunk = chunk
                content = chunk.get('message', {}).get('content', '') if isinstance(chunk, dict) else getattr(chunk.message, 'content', '')
                if content:
                    self.chunkReceived.emit(content)
            
            # Extract statistics from the last chunk
            stats = {}
            if lastChunk:
                statKeys = ['total_duration', 'load_duration', 'prompt_eval_count', 'prompt_eval_duration', 'eval_count', 'eval_duration']
                if isinstance(lastChunk, dict):
                    stats = {k: lastChunk.get(k) for k in statKeys if k in lastChunk}
                else:
                    stats = {k: getattr(lastChunk, k, None) for k in statKeys if hasattr(lastChunk, k)}

            self.finished.emit(stats)
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._isRunning = False


class AIChatDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Chat")
        self.resize(600, 700)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowStaysOnTopHint)

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

        bottomLayout = QHBoxLayout()
        self.statusLabel = QLabel("Ready")
        self.statusLabel.setStyleSheet("color: #7a8699; font-style: italic;")
        bottomLayout.addWidget(self.statusLabel)

        self.statsLabel = QLabel("")
        self.statsLabel.setStyleSheet("color: #7a8699; font-style: italic;")
        self.statsLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bottomLayout.addWidget(self.statsLabel)

        layout.addLayout(bottomLayout)

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
            self.statsLabel.clear()

    def onChunkReceived(self, chunk):
        if not self.worker:
            return
        self.currentResponse += chunk
        self.updateHistory(streaming=True)

    def onFinished(self, stats):
        if not self.worker:
            return
        self.messages.append({'role': 'assistant', 'content': self.currentResponse, 'stats': stats})
        self.worker = None
        self.currentResponse = ""
        self.statusLabel.setText("Ready")
        
        if stats:
            promptTokens = stats.get('prompt_eval_count', 0)
            evalTokens = stats.get('eval_count', 0)
            totalUsed = promptTokens + evalTokens
            contextLimit = engine.getContextLimit()
            residual = contextLimit - totalUsed
            percent = (residual / contextLimit * 100) if contextLimit > 0 else 0
            statsLine = (
                f"Context: {totalUsed} tokens "
                f"({promptTokens} prompt, {evalTokens} response) • "
                f"{percent:.1f}% free"
            )
            self.statsLabel.setText(statsLine)
        
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
            if not content:
                content = "Thinking...maybe hanging..."
            
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
