const assert = require("assert");
const vscode = require("vscode");

exports.run = async function run() {
  const ext = vscode.extensions.getExtension("repopilot.repopilot");
  await ext.activate();
  const root = vscode.workspace.workspaceFolders[0].uri;
  const uri = vscode.Uri.joinPath(root, process.env.REPOPILOT_TEST_FILE);
  await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(uri));

  const t0 = Date.now();
  await vscode.commands.executeCommand("repopilot.reviewWorking");
  const problems = vscode.languages.getDiagnostics(uri).filter((d) => d.source === "RepoPilot");
  console.log(`review took ${((Date.now() - t0) / 1000).toFixed(1)}s`);
  for (const d of problems) {
    console.log(`problem: line ${d.range.start.line + 1} [${vscode.DiagnosticSeverity[d.severity]}] ${d.message}`);
  }
  assert.ok(problems.length > 0, "the review published no findings to the Problems panel");

  const lenses = await vscode.commands.executeCommand("vscode.executeCodeLensProvider", uri);
  const titles = lenses.map((l) => l.command && l.command.title).filter(Boolean);
  console.log(`codelens: ${titles.join(" | ")}`);
  assert.ok(titles.some((t) => t.startsWith("Blast radius:")), "no blast-radius CodeLens");
};
