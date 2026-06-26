import ollama
import os
import json
import copy

import markdown
from .qt import *

from ..ai import engine
from ..core.settings import settings, RIG_BUILDER_PATH

from pygments.formatters import HtmlFormatter
from ..core.logger import logger

STARTUP_MESSAGE = """
I'm your **Rig Builder** assistant. I'm not very smart, but I'll do my best to help you. 
A number of tools available for me, so don't hesitate to ask me to do something.
I hope I don't break anything. Let's try!
"""

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
        self.numToolCalls = 10

    def run(self):
        try:
            for eventType, data in engine.chatStreamWithTools(self.messages, self.temperature, self.numToolCalls):
                if not self._isRunning:
                    return
                
                if eventType == 'chunk':
                    self.chunkReceived.emit(data)
                elif eventType == 'tool_calls':
                    self.toolCallUpdate.emit(data)
                elif eventType == 'tool_result':
                    self.toolResultUpdate.emit(data)
                elif eventType == 'stats':
                    self.finished.emit(data)
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._isRunning = False


class AIChatDialog(QDialog):
    beforeSendMessage = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Chat")
        self.resize(600, 700)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowStaysOnTopHint)

        self.messages = []
        self.currentResponse = ""
        self.worker = None
        self.aiToolsContext = {}

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
        self.setupAIChatTools()

        # Cache highlighter CSS
        formatter = HtmlFormatter(style='monokai')
        self._highlighterCss = formatter.get_style_defs('.codehilite')
        self._highlighterCss += "\n.codehilite { background-color: transparent !important; }"

    def saveChat(self):
        path = os.path.join(settings.workspacePath, "chat.txt")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.messages, f, indent=2, ensure_ascii=False)

    def loadChat(self):
        path = os.path.join(settings.workspacePath, "chat.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                self.messages = json.load(f)
        else:
            self.messages = []
        
        self.updateHistory()

    def sendMessage(self):
        text = self.input.toPlainText().strip()
        if not text or self.worker:
            return

        self.beforeSendMessage.emit()

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
            self.updateHistory()
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

    def _formatThinking(self, content):
        """Format <think> tags into a blockquote style."""
        if "<think>" in content:
            if "</think>" in content:
                content = content.replace("<think>", "\n\n> **Thinking:**\n> ")
                content = content.replace("</think>", "\n\n---\n\n")
            else:
                # Still thinking
                content = content.replace("<think>", "\n\n> **Thinking:**\n> ")
                content += "\n> ..."
        return content

    def _formatToolCalls(self, toolCalls):
        """Format tool calls into a readable string."""
        calls = []
        for tc in toolCalls:
            if isinstance(tc, dict):
                func = tc.get('function', {})
                name = func.get('name', 'unknown')
                args = func.get('arguments', {})
            else:
                func = getattr(tc, 'function', None)
                name = getattr(func, 'name', 'unknown')
                args = getattr(func, 'arguments', {})
            
            if args:
                try:
                    if isinstance(args, str):
                        args = json.loads(args)
                    argParts = []
                    for k, v in args.items():
                        val = json.dumps(v, ensure_ascii=False)
                        if len(val) > 100:
                            val = val[:100] + "..."
                        argParts.append(f"{k}={val}")
                    calls.append(f"`{name}({', '.join(argParts)})`")
                except:
                    calls.append(f"`{name}(...)`")
            else:
                calls.append(f"`{name}()`")
        
        return f"> 🛠️ **Calling Tools:** {', '.join(calls)}"

    def _formatMessageToMarkdown(self, msg):
        """Convert a message object to a Markdown string."""
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        formattedContent = self._formatThinking(content)
        
        toolCalls = msg.get('tool_calls')
        if toolCalls:
            toolLine = self._formatToolCalls(toolCalls)
            if not formattedContent:
                formattedContent = toolLine
            else:
                formattedContent += f"\n\n{toolLine}"
        elif not formattedContent and role == 'assistant':
            formattedContent = "Thinking...maybe hanging..."
        
        if role == 'user':
            return f"### 👤 {role.capitalize()}\n{formattedContent}\n\n"
        elif role == 'tool':
            return "" # Skip raw tool results in history for now
        else:
            return f"### 🤖 Assistant\n{formattedContent}\n\n"

    def updateHistory(self, streaming=False):
        """Update the chat history display."""
        if not self.messages:
            self.messages = [{'role': 'assistant', 'content': STARTUP_MESSAGE}]

        fullMd = "".join(self._formatMessageToMarkdown(msg) for msg in self.messages)

        if streaming:
            content = self._formatThinking(self.currentResponse)
            fullMd += f"### 🤖 Assistant\n{content}\n\n"
            self.history.setMarkdown(fullMd)
        else:
            htmlContent = markdown.markdown(
                fullMd, 
                extensions=['fenced_code', 'codehilite', 'tables', 'sane_lists']
            )
            self.history.setHtml(f"<style>{self._highlighterCss}</style><body>{htmlContent}</body>")

        # Scroll to bottom
        self.history.verticalScrollBar().setValue(self.history.verticalScrollBar().maximum())


    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        super().closeEvent(event)

    def setupAIChatTools(self):
        def getCurrentState() -> str:
            """
            Get the current state of Rig Builder.
            Useful for understanding the context the user is currently working in.
            Returns the selected host and the currently selected module in the tree (its name and documentation),
            and the python imports defined in the module's run code.
            Use this to understand what the user is currently selecting or working on.
            """
            m = self.aiToolsContext["selectedModule"]
            imports = []
            if m:
                for l in self.aiToolsContext["code"].splitlines():
                    if not l.strip():
                        continue
                    if l.startswith("import") or l.startswith("from"):
                        imports.append(l)
                    else:
                        break

            state = f'''
            Host: {self.aiToolsContext["host"]}, use appropriate coding standards for this host.
            Selected module: {m.name() if m else 'No module'}
            Module documentation:{'\n' + m.doc() if m else 'No documentation'}
            Imports: {'; '.join(imports) if imports else 'No imports'}
            Selected code:{'\n' + self.aiToolsContext["selectedCode"] if m else "Nothing selected"}
            '''
            return state

        def getCurrentModuleCode() -> str:
            """
            Get currently selected module code.
            Variables starting with '@' (e.g., @nodeName) represent module attributes.
            Returns the code as a string.
            """
            if not self.aiToolsContext["selectedModule"]:
                return "Code is not available"

            return self.aiToolsContext["code"]

        def queryModules(query: str) -> str:
            """
            Search for modules in the current workspace by name, description, or functionality.
            This uses a semantic vector search, so you can describe what the module does in natural language.
            Use this to find existing modules or to understand what is available.
            Returns a list of matching module paths and their relevance scores.
            """
            from ..moduleIndexer import ModuleIndexer
            import asyncio

            indexer = ModuleIndexer(os.path.join(settings.workspacePath, "moduleIndex.json"))
            indexer.refresh()
            
            try:
                results = asyncio.run(indexer.search(query, k=10))

                if not results:
                    return "No results found"
                
                output = [f"{path} (score: {score:.2f})" for path, score in results if score > 0.5]
                return "\n".join(output)

            except Exception as e:
                return f"Error during semantic search: {e}"

        def readFile(path: str) -> str:
            """
            Read a file and return its content, or list directory entries if path is a directory.
            Returns full absolute paths when listing a directory.
            """
            if not os.path.exists(path):
                return f"File not found: {path}"

            if os.path.isdir(path):
                entries = os.listdir(path)
                return "\n".join(os.path.join(path, e) for e in entries)

            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()

            except Exception as e:
                return f"Error reading file: {e}"
                
        engine.AITools.getCurrentState = getCurrentState
        engine.AITools.queryModules = queryModules
        engine.AITools.readFile = readFile
        engine.AITools.getCurrentModuleCode = getCurrentModuleCode

