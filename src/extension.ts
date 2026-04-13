import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

let statusBarItem: vscode.StatusBarItem;
let diagnosticCollection: vscode.DiagnosticCollection;       // syntax + semantic hints
let generationDiagnostics: vscode.DiagnosticCollection;      // generation failure warnings
let debounceTimer: NodeJS.Timeout | undefined;

export function activate(context: vscode.ExtensionContext) {
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    context.subscriptions.push(statusBarItem);

    diagnosticCollection = vscode.languages.createDiagnosticCollection('seq');
    context.subscriptions.push(diagnosticCollection);

    generationDiagnostics = vscode.languages.createDiagnosticCollection('seq-generation');
    context.subscriptions.push(generationDiagnostics);

    // Validate already-open documents
    vscode.workspace.textDocuments.forEach(doc => {
        if (isSeqDoc(doc)) { validateDocument(doc, context.extensionPath); }
    });

    context.subscriptions.push(
        vscode.workspace.onDidOpenTextDocument(doc => {
            if (isSeqDoc(doc)) { validateDocument(doc, context.extensionPath); }
        })
    );

    context.subscriptions.push(
        vscode.workspace.onDidChangeTextDocument(e => {
            if (!isSeqDoc(e.document)) { return; }
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                validateDocument(e.document, context.extensionPath);
            }, 500);
        })
    );

    context.subscriptions.push(
        vscode.workspace.onDidCloseTextDocument(doc => {
            diagnosticCollection.delete(doc.uri);
            generationDiagnostics.delete(doc.uri);
        })
    );

    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument(doc => {
            if (isSeqDoc(doc)) {
                generateAndPreview(doc.fileName, context.extensionPath, false);
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('drawioseq.generate', () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor || !isSeqDoc(editor.document)) {
                vscode.window.showErrorMessage('Open a .seq file first.');
                return;
            }
            generateAndPreview(editor.document.fileName, context.extensionPath, false);
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('drawioseq.preview', () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor || !isSeqDoc(editor.document)) {
                vscode.window.showErrorMessage('Open a .seq file first.');
                return;
            }
            generateAndPreview(editor.document.fileName, context.extensionPath, true);
        })
    );
}

function isSeqDoc(doc: vscode.TextDocument): boolean {
    return (doc.languageId === 'seq' || doc.fileName.endsWith('.seq'))
        && doc.uri.scheme === 'file';  // ignore untitled:, vscode-remote:, etc.
}

// ─── Security helpers ────────────────────────────────────────────────────────

const MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024; // 1 MB
const SUBPROCESS_TIMEOUT_MS = 15_000;         // 15 seconds
const MAX_STDERR_LEN = 500;                   // chars shown to user

/**
 * Validates a .seq file path before passing it to the Python subprocess.
 * Returns an error message string if invalid, null if safe to proceed.
 *
 * Checks:
 *   - No null bytes (can bypass extension checks on some platforms)
 *   - Correct .seq extension
 *   - Resolves symlinks and verifies the real path is inside a workspace folder
 *   - File does not exceed MAX_FILE_SIZE_BYTES
 */
function validateSeqPath(seqFilePath: string): string | null {
    if (!seqFilePath || typeof seqFilePath !== 'string') {
        return 'Invalid file path.';
    }

    if (seqFilePath.includes('\0')) {
        return 'File path contains null bytes.';
    }

    if (!seqFilePath.endsWith('.seq')) {
        return 'File must have a .seq extension.';
    }

    // Resolve symlinks so a symlink pointing outside the workspace is caught
    let realPath: string;
    try {
        realPath = fs.realpathSync(seqFilePath);
    } catch {
        return 'Cannot resolve file path — file may not exist.';
    }

    // Must sit inside at least one workspace folder
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) {
        return 'No workspace folder is open.';
    }

    const inWorkspace = folders.some(f => {
        const base = f.uri.fsPath;
        return realPath === base || realPath.startsWith(base + path.sep);
    });

    if (!inWorkspace) {
        return 'File is outside the workspace — generation refused.';
    }

    // Reject files that are too large to prevent subprocess DoS
    try {
        const stat = fs.statSync(realPath);
        if (stat.size > MAX_FILE_SIZE_BYTES) {
            return `File exceeds the ${MAX_FILE_SIZE_BYTES / 1024} KB size limit.`;
        }
    } catch {
        return 'Cannot stat file.';
    }

    return null; // all good
}

/**
 * Derives the output .drawio path and verifies it stays in the same
 * directory as the input file (prevents any path manipulation edge cases).
 */
function deriveOutputPath(seqFilePath: string): string | null {
    if (seqFilePath.includes('\0')) { return null; }

    const outputPath = seqFilePath.replace(/\.seq$/, '.drawio');

    // Output must land in the same directory as the source file
    if (path.dirname(path.resolve(outputPath)) !== path.dirname(path.resolve(seqFilePath))) {
        return null;
    }

    return outputPath;
}

/**
 * Cleans a Python traceback for display:
 * - Removes "File ..." path lines (internal, not useful to the user)
 * - Removes the "Traceback (most recent call last):" header
 * - Keeps the call chain and the final error message in full
 */
function cleanPythonTraceback(stderr: string): string {
    const lines = stderr.trim().split('\n').filter(line => {
        const t = line.trim();
        return t.length > 0
            && !t.startsWith('File "')
            && !t.startsWith('Traceback (most recent');
    });
    return lines.join('\n').trim() || stderr.trim();
}

/**
 * Finds the index of the last non-empty, non-comment line in a .seq file.
 */
function lastContentLine(filePath: string): number {
    try {
        const lines = fs.readFileSync(filePath, 'utf8').split('\n');
        for (let i = lines.length - 1; i >= 0; i--) {
            const t = lines[i].trim();
            if (t.length > 0 && !t.startsWith('//')) { return i; }
        }
    } catch { /* fall through */ }
    return 0;
}

// ─── Validation ──────────────────────────────────────────────────────────────

async function validateDocument(doc: vscode.TextDocument, extensionPath: string): Promise<void> {
    // Skip non-file URIs (untitled, remote, virtual file systems)
    if (doc.uri.scheme !== 'file') { return; }

    // Skip oversized documents (in-memory check before hitting the subprocess)
    const text = doc.getText();
    if (Buffer.byteLength(text, 'utf8') > MAX_FILE_SIZE_BYTES) {
        diagnosticCollection.delete(doc.uri);
        return;
    }

    const python = await findPython();
    if (!python) {
        diagnosticCollection.set(doc.uri, runSemanticChecks(doc));
        return;
    }

    const checkScript = path.join(extensionPath, 'vendor', 'seqgen', 'check.py');
    const vendorDir   = path.join(extensionPath, 'vendor', 'seqgen');

    const child = cp.execFile(
        python,
        [checkScript],
        { cwd: vendorDir, timeout: SUBPROCESS_TIMEOUT_MS },
        (_err, stdout) => {
            let syntaxDiags: vscode.Diagnostic[] = [];
            try {
                const errors: { line: number; col: number; message: string }[] = JSON.parse(stdout || '[]');
                syntaxDiags = errors.map(e => {
                    const lineIdx  = Math.max(0, e.line - 1);
                    const colIdx   = Math.max(0, e.col - 1);
                    const lineText = doc.lineAt(Math.min(lineIdx, doc.lineCount - 1)).text;
                    const range    = new vscode.Range(lineIdx, colIdx, lineIdx, Math.max(colIdx + 1, lineText.length));
                    const diag     = new vscode.Diagnostic(range, e.message, vscode.DiagnosticSeverity.Error);
                    diag.source    = 'drawioseq';
                    return diag;
                });
            } catch { /* ignore JSON parse failure */ }

            const semanticDiags = syntaxDiags.length === 0 ? runSemanticChecks(doc) : [];
            diagnosticCollection.set(doc.uri, [...syntaxDiags, ...semanticDiags]);
        }
    );

    child.stdin?.end(text, 'utf8');
}

function runSemanticChecks(doc: vscode.TextDocument): vscode.Diagnostic[] {
    const diags: vscode.Diagnostic[] = [];
    const declaredParticipants  = new Set<string>();
    const activatedParticipants = new Map<string, number>(); // name → line index
    const blockStack: { keyword: string; line: number }[] = [];

    const BLOCK_OPENERS = new Set(['opt', 'loop', 'break', 'critical', 'alt', 'par', 'group']);

    for (let i = 0; i < doc.lineCount; i++) {
        const raw     = doc.lineAt(i).text;
        const trimmed = raw.replace(/\/\/.*$/, '').trim();
        if (!trimmed) { continue; }

        const participantM = trimmed.match(/^participant\s+([A-Za-z0-9_]+)/);
        if (participantM) { declaredParticipants.add(participantM[1]); continue; }

        const activateM = trimmed.match(/^activate\s+(.*)/);
        if (activateM) {
            for (const name of activateM[1].trim().split(/\s+/)) {
                if (name) { activatedParticipants.set(name, i); }
            }
            continue;
        }

        const deactivateM = trimmed.match(/^deactivate\s+(.*)/);
        if (deactivateM) {
            for (const name of deactivateM[1].trim().split(/\s+/)) {
                if (name) { activatedParticipants.delete(name); }
            }
            continue;
        }

        const firstWord = trimmed.split(/\s/)[0];
        if (BLOCK_OPENERS.has(firstWord)) { blockStack.push({ keyword: firstWord, line: i }); continue; }

        if (/^end\s*$/.test(trimmed)) {
            if (blockStack.length === 0) {
                diags.push(makeHint(i, 0, 3, 'Unexpected "end" — no open block'));
            } else {
                blockStack.pop();
            }
            continue;
        }

        const msgM = trimmed.match(/^([A-Za-z0-9_]+)\s+(--?>?>?[+\-|]?)\s+([A-Za-z0-9_]+)/);
        if (msgM && declaredParticipants.size > 0) {
            const [, sender, , receiver] = msgM;
            if (!declaredParticipants.has(sender)) {
                const col = raw.indexOf(sender);
                diags.push(makeHint(i, col, col + sender.length, `Unknown participant "${sender}"`));
            }
            const receiverCol = raw.indexOf(receiver, raw.indexOf(sender) + sender.length);
            if (!declaredParticipants.has(receiver) && receiverCol >= 0) {
                diags.push(makeHint(i, receiverCol, receiverCol + receiver.length, `Unknown participant "${receiver}"`));
            }
        }
    }

    for (const block of blockStack) {
        const len = doc.lineAt(block.line).text.trim().length;
        diags.push(makeHint(block.line, 0, len, `Unclosed block "${block.keyword}" — missing "end"`));
    }

    for (const [name, lineIdx] of activatedParticipants) {
        const lineText = doc.lineAt(lineIdx).text;
        const col = Math.max(0, lineText.indexOf(name));
        diags.push(makeHint(lineIdx, col, col + name.length, `"${name}" is activated but never deactivated`));
    }

    return diags;
}

function makeHint(line: number, start: number, end: number, message: string): vscode.Diagnostic {
    const diag = new vscode.Diagnostic(new vscode.Range(line, start, line, end), message, vscode.DiagnosticSeverity.Hint);
    diag.source = 'drawioseq';
    return diag;
}

// ─── Generation ──────────────────────────────────────────────────────────────

async function generateAndPreview(seqFilePath: string, extensionPath: string, forceOpenPreview: boolean): Promise<void> {
    // Validate input path before touching the subprocess
    const pathError = validateSeqPath(seqFilePath);
    if (pathError) {
        vscode.window.showErrorMessage(`drawioseq: ${pathError}`);
        return;
    }

    const outputPath = deriveOutputPath(seqFilePath);
    if (!outputPath) {
        vscode.window.showErrorMessage('drawioseq: Could not derive a safe output path.');
        return;
    }

    const vendorDir  = path.join(extensionPath, 'vendor', 'seqgen');
    const mainScript = path.join(vendorDir, 'main.py');

    if (!fs.existsSync(mainScript)) {
        vscode.window.showErrorMessage(`drawioseq: vendor script not found at ${mainScript}`);
        return;
    }

    const python = await findPython();
    if (!python) {
        vscode.window.showErrorMessage('drawioseq: Python 3 not found. Install Python 3 and make sure it is on your PATH.');
        return;
    }

    statusBarItem.text = '$(sync~spin) drawioseq: generating...';
    statusBarItem.show();

    // Use execFile (not exec) — arguments are never passed through a shell,
    // so there is no shell injection risk even with unusual file names.
    cp.execFile(
        python,
        [mainScript, seqFilePath, '-o', outputPath],
        { cwd: vendorDir, timeout: SUBPROCESS_TIMEOUT_MS },
        async (err, _stdout, stderr) => {
            statusBarItem.hide();

            if (err) {
                const msg = cleanPythonTraceback(stderr) || err.message.slice(0, MAX_STDERR_LEN);

                statusBarItem.text = '$(error) drawioseq: generation failed';
                statusBarItem.show();
                setTimeout(() => statusBarItem.hide(), 5000);

                if (msg.includes('ModuleNotFoundError') || msg.includes("No module named 'lark'")) {
                    const docUri = vscode.Uri.file(seqFilePath);
                    const lineIdx = lastContentLine(seqFilePath);
                    const lineText = fs.readFileSync(seqFilePath, 'utf8').split('\n')[lineIdx] ?? '';
                    const genDiag = new vscode.Diagnostic(
                        new vscode.Range(lineIdx, 0, lineIdx, lineText.length || 1),
                        'drawioseq: lark is not installed. Run: pip3 install lark',
                        vscode.DiagnosticSeverity.Error
                    );
                    genDiag.source = 'drawioseq';
                    generationDiagnostics.set(docUri, [genDiag]);
                } else {
                    // Place a red squiggle on the last content line with the
                    // full cleaned traceback — no popup, hover to read the error
                    const docUri = vscode.Uri.file(seqFilePath);
                    const lineIdx = lastContentLine(seqFilePath);
                    const lineText = fs.readFileSync(seqFilePath, 'utf8').split('\n')[lineIdx] ?? '';
                    const fullMsg = cleanPythonTraceback(stderr) || msg;
                    const genDiag = new vscode.Diagnostic(
                        new vscode.Range(lineIdx, 0, lineIdx, lineText.length || 1),
                        fullMsg,
                        vscode.DiagnosticSeverity.Error
                    );
                    genDiag.source = 'drawioseq';
                    generationDiagnostics.set(docUri, [genDiag]);
                }
                return;
            }

            // Clear the generation-failure diagnostic on success
            generationDiagnostics.delete(vscode.Uri.file(seqFilePath));

            statusBarItem.text = '$(check) drawioseq: generated';
            statusBarItem.show();
            setTimeout(() => statusBarItem.hide(), 3000);

            const outputUri = vscode.Uri.file(outputPath);
            if (forceOpenPreview || !isFileVisibleInEditor(outputPath)) {
                await openDrawioPreview(outputUri);
            }
        }
    );
}

async function openDrawioPreview(uri: vscode.Uri): Promise<void> {
    await vscode.commands.executeCommand('vscode.open', uri, { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true });
}

function isFileVisibleInEditor(fsPath: string): boolean {
    return vscode.window.tabGroups.all
        .flatMap(g => g.tabs)
        .some(tab => {
            if (tab.input instanceof vscode.TabInputCustom || tab.input instanceof vscode.TabInputText) {
                return tab.input.uri.fsPath === fsPath;
            }
            return false;
        });
}

async function findPython(): Promise<string | null> {
    for (const candidate of ['python3', 'python']) {
        if (await checkPython(candidate)) { return candidate; }
    }
    return null;
}

function checkPython(bin: string): Promise<boolean> {
    return new Promise(resolve => {
        cp.execFile(bin, ['--version'], { timeout: 5_000 }, (err, stdout, stderr) => {
            resolve(!err && (stdout + stderr).startsWith('Python 3'));
        });
    });
}

export function deactivate() {}
