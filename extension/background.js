const ext = typeof browser !== "undefined" ? browser : chrome;

function panelUrl(hash) {
  const base = ext.runtime.getURL("home.html");
  return hash ? `${base}${hash}` : `${base}#/home`;
}

function openPanel(path) {
  ext.tabs.create({ url: panelUrl(path || "#/home") });
}

ext.action.onClicked.addListener(() => {
  openPanel("#/home");
});

ext.omnibox.onInputEntered.addListener((text) => {
  const raw = (text || "home").trim();
  if (raw.startsWith("reticulum://") || raw.startsWith("ext+reticulum://")) {
    openPanel("#/" + raw.replace(/^(ext\+)?reticulum:\/\//, ""));
    return;
  }
  openPanel("#/" + raw.replace(/^\/+/, ""));
});

ext.omnibox.onInputChanged.addListener((_text, suggest) => {
  suggest([
    { content: "home", description: "Panel Reticulum" },
    { content: "setup", description: "Wybór rNode w sieci" },
    { content: "nodes", description: "Rozgłoszone node'y" },
  ]);
});
