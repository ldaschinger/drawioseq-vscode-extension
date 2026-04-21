import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';

let statusBarItem: vscode.StatusBarItem;
let diagnosticCollection: vscode.DiagnosticCollection;       // syntax + semantic hints
let generationDiagnostics: vscode.DiagnosticCollection;      // generation failure warnings
let debounceTimer: NodeJS.Timeout | undefined;
// Track which documents have already been offered a conversion so we don't spam
const conversionOffered = new Set<string>();

export function activate(context: vscode.ExtensionContext) {
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    context.subscriptions.push(statusBarItem);

    diagnosticCollection = vscode.languages.createDiagnosticCollection('seq');
    context.subscriptions.push(diagnosticCollection);

    generationDiagnostics = vscode.languages.createDiagnosticCollection('seq-generation');
    context.subscriptions.push(generationDiagnostics);

    // Validate already-open documents and offer conversion for old syntax
    vscode.workspace.textDocuments.forEach(doc => {
        if (isSeqDoc(doc)) {
            validateDocument(doc, context.extensionPath);
            offerConversion(doc);
        }
    });

    context.subscriptions.push(
        vscode.workspace.onDidOpenTextDocument(doc => {
            if (isSeqDoc(doc)) {
                validateDocument(doc, context.extensionPath);
                offerConversion(doc);
            }
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
            conversionOffered.delete(doc.uri.toString());
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

// ─── Old-syntax converter ────────────────────────────────────────────────────

/**
 * Converts pre-2026 .seq syntax to the current syntax so the Python backend
 * can parse both old and new files transparently.
 *
 * Conversions applied:
 *   title "text" [width N height N]  →  title [width N height N]: text
 *   participant "Display" as ALIAS   →  participant ALIAS: Display
 *   participant Name as ALIAS        →  participant ALIAS: Name
 *   note on NAME [attrs]\n…\nend note  →  note on NAME [attrs]: …
 *   frame extend N                   →  extend frame N
 *   block keyword "quoted label"     →  block keyword unquoted label
 *   \n in labels                     →  <br/>
 */
function convertOldSyntax(text: string): string {
    const lines = text.split('\n');
    const out: string[] = [];
    let i = 0;
    while (i < lines.length) {
        const line = lines[i];
        const indent = line.match(/^(\s*)/)?.[1] ?? '';
        const trimmed = line.trim();

        // title "text" [width N height N]
        let m = trimmed.match(/^title\s+"((?:[^"\\]|\\.)*)"\s*((?:(?:width|height)\s+[0-9]+\s*)*)$/);
        if (m) {
            const titleText = m[1].replace(/\\n/g, '<br/>');
            const attrs = m[2].trim();
            out.push(indent + (attrs ? `title ${attrs}: ${titleText}` : `title: ${titleText}`));
            i++; continue;
        }

        // participant "Display" [width/spacing N]* [as ALIAS]
        m = trimmed.match(/^participant\s+"((?:[^"\\]|\\.)*)"\s*((?:(?:width|spacing)\s+[0-9]+\s*)*)(?:as\s+([A-Za-z0-9_]+))?$/);
        if (m) {
            const display = m[1].replace(/\\n/g, '<br/>');
            const attrs = m[2].trim();
            const alias = m[3];
            if (alias) {
                out.push(indent + (attrs ? `participant ${alias} ${attrs}: ${display}` : `participant ${alias}: ${display}`));
            } else {
                out.push(line); // quoted-only form is still valid in new syntax
            }
            i++; continue;
        }

        // participant Name [width/spacing N]* as ALIAS
        m = trimmed.match(/^participant\s+([A-Za-z0-9_]+)((?:\s+(?:width|spacing)\s+[0-9]+)*)\s+as\s+([A-Za-z0-9_]+)$/);
        if (m) {
            const name = m[1];
            const attrs = m[2].trim();
            const alias = m[3];
            out.push(indent + (attrs ? `participant ${alias} ${attrs}: ${name}` : `participant ${alias}: ${name}`));
            i++; continue;
        }

        // note on NAME [attrs]   (block form — no trailing colon)
        m = trimmed.match(/^(note on\s+[A-Za-z0-9_]+(?:\s+(?:dx|dy|width|height)\s+-?[0-9]+)*)$/);
        if (m) {
            const noteDecl = m[1];
            const bodyLines: string[] = [];
            i++;
            while (i < lines.length && lines[i].trim() !== 'end note') {
                const bt = lines[i].trim();
                if (bt) { bodyLines.push(bt); }
                i++;
            }
            if (i < lines.length) { i++; } // skip "end note"
            const noteText = bodyLines.join('<br/>').replace(/\\n/g, '<br/>');
            out.push(indent + `${noteDecl}: ${noteText}`);
            continue;
        }

        // frame extend N  →  extend frame N
        m = trimmed.match(/^frame extend\s+(-?[0-9]+)$/);
        if (m) {
            out.push(indent + `extend frame ${m[1]}`);
            i++; continue;
        }

        // block keyword "quoted label"  →  keyword unquoted label
        m = trimmed.match(/^(opt|loop|break|alt|par|group|else|and|section)\s+"((?:[^"\\]|\\.)*)"(.*)$/);
        if (m) {
            const label = m[2].replace(/\\"/g, '"').replace(/\\n/g, '<br/>');
            out.push(indent + `${m[1]} ${label}${m[3]}`);
            i++; continue;
        }

        // \n in message labels
        out.push(line.replace(/\\n/g, '<br/>'));
        i++;
    }
    return out.join('\n');
}

/** Returns true if the text contains at least one old-syntax construct. */
function isOldSyntax(text: string): boolean {
    return (
        /^[ \t]*title\s+"/.test(text)                        ||  // title "..."
        /^[ \t]*participant\s+"[^"]*"\s+as\s+/m.test(text)  ||  // participant "X" as Y
        /^[ \t]*participant\s+\w+\s+as\s+/m.test(text)      ||  // participant X as Y
        /^[ \t]*frame extend\s+-?[0-9]+/m.test(text)        ||  // frame extend N
        /^[ \t]*end note\s*$/m.test(text)                   ||  // end note (block notes)
        /^[ \t]*(?:opt|loop|break|alt|par|group|else|and|section)\s+"/m.test(text)  // quoted block labels
    );
}

/**
 * If the document uses old syntax and hasn't been offered a conversion yet,
 * shows a one-time notification with a "Convert" button. Applying the edit
 * replaces the full document content with the converted text.
 */
async function offerConversion(doc: vscode.TextDocument): Promise<void> {
    const key = doc.uri.toString();
    if (conversionOffered.has(key)) { return; }
    const text = doc.getText();
    if (!isOldSyntax(text)) { return; }

    conversionOffered.add(key);

    const choice = await vscode.window.showInformationMessage(
        'This .seq file uses old syntax. Convert it to the current syntax?',
        'Convert',
        'Keep as-is'
    );

    if (choice !== 'Convert') { return; }

    const converted = convertOldSyntax(text);
    const edit = new vscode.WorkspaceEdit();
    edit.replace(doc.uri, new vscode.Range(0, 0, doc.lineCount, 0), converted);
    await vscode.workspace.applyEdit(edit);

    // Save the document so the conversion is persisted to disk
    await doc.save();
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

    child.stdin?.end(convertOldSyntax(text), 'utf8');
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

        // new syntax: participant ALIAS [attrs] [: display]
        let participantM = trimmed.match(/^participant\s+([A-Za-z0-9_]+)((?:\s+(?:width|spacing)\s+[0-9]+)*)(?:\s+as\s+[A-Za-z0-9_]+)?/);
        // old syntax: participant "Display" [attrs] [as ALIAS]
        if (!participantM) {
            const oldQ = trimmed.match(/^participant\s+"[^"]*"(?:\s+(?:width|spacing)\s+[0-9]+)*(?:\s+as\s+([A-Za-z0-9_]+))?/);
            if (oldQ) { if (oldQ[1]) { declaredParticipants.add(oldQ[1]); } continue; }
            const oldA = trimmed.match(/^participant\s+[A-Za-z0-9_]+(?:\s+(?:width|spacing)\s+[0-9]+)*\s+as\s+([A-Za-z0-9_]+)/);
            if (oldA) { declaredParticipants.add(oldA[1]); continue; }
        }
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

        if (/^end(\s+note)?\s*$/.test(trimmed)) {
            if (trimmed === 'end') {
                if (blockStack.length === 0) {
                    diags.push(makeHint(i, 0, 3, 'Unexpected "end" — no open block'));
                } else {
                    blockStack.pop();
                }
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

    // Convert old syntax on-the-fly: write to a temp file so main.py always
    // receives new-syntax content while the output still lands next to the source.
    let inputForPython = seqFilePath;
    let tempSeqPath: string | null = null;
    try {
        const originalText = fs.readFileSync(seqFilePath, 'utf8');
        const convertedText = convertOldSyntax(originalText);
        if (convertedText !== originalText) {
            tempSeqPath = path.join(os.tmpdir(), `drawioseq_${Date.now()}.seq`);
            fs.writeFileSync(tempSeqPath, convertedText, 'utf8');
            inputForPython = tempSeqPath;
        }
    } catch { /* fall through: use original file */ }

    // Use execFile (not exec) — arguments are never passed through a shell,
    // so there is no shell injection risk even with unusual file names.
    cp.execFile(
        python,
        [mainScript, inputForPython, '-o', outputPath],
        { cwd: vendorDir, timeout: SUBPROCESS_TIMEOUT_MS },
        async (err, _stdout, stderr) => {
            if (tempSeqPath) { try { fs.unlinkSync(tempSeqPath); } catch { /* ignore */ } }
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
