import * as assert from 'assert';
import * as cp from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

// Path to the vendored generator (relative to compiled test output at out/test/)
const VENDOR_MAIN = path.resolve(__dirname, '../../vendor/seqgen/main.py');

function runGenerator(seqContent: string, outputPath: string): Promise<{ code: number; stderr: string }> {
    return new Promise((resolve) => {
        const tmp = path.join(os.tmpdir(), `drawioseq-test-${Date.now()}.seq`);
        fs.writeFileSync(tmp, seqContent, 'utf8');

        cp.execFile('python3', [VENDOR_MAIN, tmp, '-o', outputPath], (err, _stdout, stderr) => {
            fs.unlinkSync(tmp);
            resolve({ code: typeof err?.code === 'number' ? err.code : 0, stderr });
        });
    });
}

suite('Vendor script', () => {
    test('main.py exists', () => {
        assert.ok(fs.existsSync(VENDOR_MAIN), `vendor script not found: ${VENDOR_MAIN}`);
    });

    test('lark is importable by python3', (done) => {
        cp.execFile('python3', ['-c', 'import lark'], (err, _stdout, stderr) => {
            assert.strictEqual(err, null, `lark not installed: ${stderr}\nRun: pip3 install lark`);
            done();
        });
    });
});

suite('Generator output', () => {
    let outFile: string;

    setup(() => {
        outFile = path.join(os.tmpdir(), `drawioseq-test-${Date.now()}.drawio`);
    });

    teardown(() => {
        if (fs.existsSync(outFile)) {
            fs.unlinkSync(outFile);
        }
    });

    test('generates a .drawio file for a minimal diagram', async () => {
        const { code } = await runGenerator(
            'participant Alice\nparticipant Bob\nAlice -> Bob: Hello\n',
            outFile
        );
        assert.strictEqual(code, 0);
        assert.ok(fs.existsSync(outFile), '.drawio file was not created');
    });

    test('output is valid XML with mxfile root', async () => {
        await runGenerator(
            'participant Alice\nparticipant Bob\nAlice -> Bob: Hello\n',
            outFile
        );
        const content = fs.readFileSync(outFile, 'utf8');
        assert.ok(content.startsWith('<mxfile'), 'output does not start with <mxfile>');
        assert.ok(content.includes('<diagram'), 'output missing <diagram> element');
        assert.ok(content.includes('mxCell'), 'output missing mxCell elements');
    });

    test('title statement appears in output', async () => {
        await runGenerator(
            'title: My Diagram\nparticipant Alice\n',
            outFile
        );
        const content = fs.readFileSync(outFile, 'utf8');
        assert.ok(content.includes('My Diagram'), 'title text not found in output');
    });

    test('participant names appear in output', async () => {
        await runGenerator(
            'participant Alice\nparticipant Bob\n',
            outFile
        );
        const content = fs.readFileSync(outFile, 'utf8');
        assert.ok(content.includes('Alice'), 'participant Alice not found in output');
        assert.ok(content.includes('Bob'), 'participant Bob not found in output');
    });

    test('message text appears in output', async () => {
        await runGenerator(
            'participant Alice\nparticipant Bob\nAlice -> Bob: Specific message text\n',
            outFile
        );
        const content = fs.readFileSync(outFile, 'utf8');
        assert.ok(content.includes('Specific message text'), 'message text not found in output');
    });

    test('returns error for invalid .seq syntax', async () => {
        const { code, stderr } = await runGenerator(
            'this is not valid seq syntax !!!\n',
            outFile
        );
        assert.notStrictEqual(code, 0, 'expected non-zero exit for invalid input');
        assert.ok(stderr.length > 0, 'expected error output for invalid input');
    });

    test('activation and deactivation produce activation bars', async () => {
        await runGenerator([
            'participant Alice',
            'participant Bob',
            'activate Alice',
            'Alice ->+ Bob: call',
            'Bob -->>- Alice: response',
            'deactivate Alice',
        ].join('\n') + '\n',
            outFile
        );
        const content = fs.readFileSync(outFile, 'utf8');
        // Activation bars are plain vertex cells parented to a lifeline
        assert.ok(content.includes('portConstraint'), 'expected activation bar style in output');
    });

    test('alt frame produces umlFrame shape', async () => {
        await runGenerator([
            'participant Alice',
            'participant Bob',
            'alt condition',
            '  Alice -> Bob: yes',
            'else',
            '  Alice -> Bob: no',
            'end',
        ].join('\n') + '\n',
            outFile
        );
        const content = fs.readFileSync(outFile, 'utf8');
        assert.ok(content.includes('umlFrame'), 'expected umlFrame shape for alt block');
        assert.ok(content.includes('alt'), 'expected alt label in output');
    });
});
