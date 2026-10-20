// End-to-end test: launches VS Code with this extension against a real repository and a running
// `repopilot serve`, runs the review command, and checks the Problems panel and the CodeLens.
//   REPOPILOT_TEST_REPO=/path/to/git/repo node test/runTest.js
const os = require("os");
const path = require("path");
const { runTests } = require("@vscode/test-electron");

const repo = process.env.REPOPILOT_TEST_REPO;
if (!repo) throw new Error("Set REPOPILOT_TEST_REPO to a git repository with uncommitted changes.");
const scratch = path.join(os.tmpdir(), "repopilot-vscode-test");
const installed = "/Applications/Visual Studio Code.app/Contents/MacOS/Code";

runTests({
  vscodeExecutablePath: process.env.VSCODE_PATH || (process.platform === "darwin" ? installed : undefined),
  extensionDevelopmentPath: path.resolve(__dirname, ".."),
  extensionTestsPath: path.resolve(__dirname, "suite.js"),
  launchArgs: [repo, "--disable-extensions", `--user-data-dir=${scratch}/data`, `--extensions-dir=${scratch}/ext`],
  extensionTestsEnv: { REPOPILOT_TEST_FILE: process.env.REPOPILOT_TEST_FILE || "shop.py" },
}).catch((err) => {
  console.error(err);
  process.exit(1);
});
