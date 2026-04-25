import ollama
import os
import json
from ..qt import *
from ..ai import engine
from ..settings import settings
from .. import workspace
import markdown
from pygments.formatters import HtmlFormatter
import copy

class AITools:
    """Registry for AI tools. Add new staticmethods here with type hints and docstrings."""

    @classmethod
    def getTools(cls):
        tools = []
        for name in dir(cls):
            if not name.startswith('_') and name not in ['getTools', 'execute']:
                attr = getattr(cls, name)
                if callable(attr):
                    tools.append(attr)
        return tools

    @classmethod
    def execute(cls, name: str, args: dict):
        if hasattr(cls, name):
            func = getattr(cls, name)
            if callable(func):
                try:
                    return func(**args)
                except Exception as e:
                    return f"Error executing {name}: {str(e)}"
        return f"Unknown tool: {name}"

class AIChatWorker(QThread):
    chunkReceived = Signal(str)
    finished = Signal(dict)
    error = Signal(str)
    toolCallUpdate = Signal(list)
    toolResultUpdate = Signal(dict)

    def __init__(self, messages, temperature=0.7):
        super().__init__()
        self.messages = copy.deepcopy(messages)
        self.temperature = temperature
        self._isRunning = True

    def run(self):
        try:
            totalMessages = engine.getChatMessages(self.messages)
            tools = AITools.getTools()

            lastChunk = None
            
            for turn in range(5): # Allow several tool-calling turns
                hasToolCalls = False
                currentToolCalls = []
                streamedContent = ""

                for chunk in ollama.chat(
                    model=settings.ollamaModel,
                    messages=totalMessages,
                    stream=True,
                    options={'temperature': self.temperature},
                    tools=tools
                ):
                    if not self._isRunning:
                        return
                    
                    lastChunk = chunk
                    
                    if isinstance(chunk, dict):
                        msg = chunk.get('message', {})
                        content = msg.get('content', '')
                        tc = msg.get('tool_calls', [])
                    else:
                        msg = getattr(chunk, 'message', None)
                        content = getattr(msg, 'content', '') if msg else ''
                        tc = getattr(msg, 'tool_calls', []) if msg else []
                    
                    if tc:
                        hasToolCalls = True
                        for call in tc:
                            if isinstance(call, dict):
                                currentToolCalls.append(call)
                            else:
                                func_obj = getattr(call, 'function', None)
                                funcName = getattr(func_obj, 'name', None)
                                args = getattr(func_obj, 'arguments', {})
                                currentToolCalls.append({
                                    'function': {
                                        'name': funcName,
                                        'arguments': args
                                    }
                                })
                    
                    if content:
                        streamedContent += content
                        self.chunkReceived.emit(content)
                        
                if hasToolCalls:
                    assistantMsg = {
                        'role': 'assistant',
                        'content': streamedContent,
                        'tool_calls': currentToolCalls
                    }
                    totalMessages.append(assistantMsg)
                    self.toolCallUpdate.emit(currentToolCalls)
                    
                    for call in currentToolCalls:
                        if not self._isRunning:
                            return
                            
                        if isinstance(call, dict):
                            funcName = call.get('function', {}).get('name')
                            args = call.get('function', {}).get('arguments', {})
                        else:
                            funcName = getattr(getattr(call, 'function', None), 'name', None)
                            args = getattr(getattr(call, 'function', None), 'arguments', {})

                        if funcName:
                            result = AITools.execute(funcName, args)
                            
                            toolMsg = {
                                'role': 'tool',
                                'content': str(result),
                                'name': funcName
                            }
                            totalMessages.append(toolMsg)
                            self.toolResultUpdate.emit(toolMsg)
                            
                    continue # Re-run chat with new tool messages
                else:
                    break # No tool calls, finish

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

    def saveChat(self):
        ws = workspace.currentWorkspace
        if not ws: 
            return

        path = os.path.join(ws.folderPath(), "chat.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.messages, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save chat: {e}")

    def loadChat(self):
        ws = workspace.currentWorkspace
        if not ws: 
            return

        self.messages = []
        path = os.path.join(ws.folderPath(), "chat.txt")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.messages = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load chat: {e}")
            
        self.updateHistory()

    def sendMessage(self):
        text = self.input.toPlainText().strip()
        if not text or self.worker:
            return

        self.input.clear()
        self.messages.append({'role': 'user', 'content': text})
        self.saveChat()
        self.updateHistory()

        self.worker = AIChatWorker(self.messages)
        self.worker.chunkReceived.connect(self.onChunkReceived)
        self.worker.toolCallUpdate.connect(self.onToolCallUpdate)
        self.worker.toolResultUpdate.connect(self.onToolResultUpdate)
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
            self.saveChat()

    def onChunkReceived(self, chunk):
        if not self.worker:
            return
        self.currentResponse += chunk
        self.updateHistory(streaming=True)

    def onToolCallUpdate(self, toolCalls):
        if not self.worker:
            return
        self.messages.append({
            'role': 'assistant',
            'content': self.currentResponse,
            'tool_calls': toolCalls
        })
        self.saveChat()
        self.currentResponse = ""
        self.updateHistory()
        self.statusLabel.setText("Executing tools...")

    def onToolResultUpdate(self, toolMsg):
        if not self.worker:
            return
        self.messages.append(toolMsg)
        self.saveChat()
        self.updateHistory()
        self.statusLabel.setText("Analyzing tool results...")

    def onFinished(self, stats):
        if not self.worker:
            return
        self.messages.append({'role': 'assistant', 'content': self.currentResponse, 'stats': stats})
        self.saveChat()
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
            role = msg.get('role', 'unknown').capitalize()
            content = msg.get('content', '')
            formattedContent = formatContent(content)
            
            if msg.get('tool_calls'):
                calls = []
                for tc in msg.get('tool_calls', []):
                    if isinstance(tc, dict):
                        name = tc.get('function', {}).get('name', 'unknown')
                    else:
                        name = getattr(getattr(tc, 'function', None), 'name', 'unknown')
                    calls.append(name)
                
                if not formattedContent:
                    formattedContent = f"> 🛠️ **Calling Tools:** `{', '.join(calls)}`"
                else:
                    formattedContent += f"\n\n> 🛠️ **Calling Tools:** `{', '.join(calls)}`"
            elif not formattedContent and role == 'Assistant':
                formattedContent = "Thinking...maybe hanging..."
            
            if msg.get('role') == 'user':
                fullMd += f"### 👤 {role}\n{formattedContent}\n\n"
            elif msg.get('role') == 'tool':
                #name = msg.get('name', 'unknown')
                #fullMd += f"### ⚙️ Tool Result ({name})\n```text\n{formattedContent}\n```\n\n"
                pass
            else:
                fullMd += f"### 🤖 Assistant\n{formattedContent}\n\n"

        if streaming:
            content = formatContent(self.currentResponse)
            fullMd += f"### 🤖 Assistant\n{content}\n\n"
            self.history.setMarkdown(fullMd)

        else:
            formatter = HtmlFormatter(style='monokai')
            css = formatter.get_style_defs('.codehilite')
            css += "\n.codehilite { background-color: transparent !important; }"
            
            htmlContent = markdown.markdown(
                fullMd, 
                extensions=['fenced_code', 'codehilite', 'tables', 'sane_lists']
            )
            
            fullHtml = f"""<style>{css}</style><body>{htmlContent}</body>"""
            
            self.history.setHtml(fullHtml)

        # Scroll to bottom
        self.history.verticalScrollBar().setValue(self.history.verticalScrollBar().maximum())

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        super().closeEvent(event)
