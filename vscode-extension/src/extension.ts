import * as vscode from "vscode";

import { ask, BlastLens, diagnostics, diffDocs, edit, getLastPanelHtml, initFeatures, nightShift, pickModels, refreshStatus, reindex, review, showBlast } from "./features";

export function activate(context: vscode.ExtensionContext): { getLastPanelHtml: () => string } {
  initFeatures(context.extensionUri);
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 90);
  status.command = "repopilot.pickModels";
  void refreshStatus(status);

  context.subscriptions.push(
    status,
    diagnostics,
    vscode.workspace.registerTextDocumentContentProvider("repopilot-diff", diffDocs),
    vscode.languages.registerCodeLensProvider({ scheme: "file" }, new BlastLens()),
    vscode.commands.registerCommand("repopilot.reviewWorking", () => review(false)),
    vscode.commands.registerCommand("repopilot.reviewStaged", () => review(true)),
    vscode.commands.registerCommand("repopilot.blastRadius", showBlast),
    vscode.commands.registerCommand("repopilot.ask", () => ask()),
    vscode.commands.registerCommand("repopilot.edit", edit),
    vscode.commands.registerCommand("repopilot.nightShift", nightShift),
    vscode.commands.registerCommand("repopilot.pickModels", () => pickModels(status)),
    vscode.commands.registerCommand("repopilot.index", reindex),
  );
  return { getLastPanelHtml };
}

export function deactivate(): void {
  diagnostics.clear();
}
