// Point the main download buttons at the right file for this computer. Without a match, they open the releases page.
(() => {
  const base = "https://github.com/Gabriel-Dalton/autohours/releases/latest/download/";
  const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || navigator.userAgent;
  const buttons = [document.getElementById("download"), ...document.querySelectorAll("[data-download]")];
  const note = document.getElementById("download-note");
  if (/win/i.test(platform)) {
    for (const b of buttons) { b.href = base + "autohours-windows.exe"; b.textContent = "Download for Windows"; }
    note.innerHTML = 'Free. Also for <a href="#all-downloads">Mac</a>. Works with <a href="https://activitywatch.net/">ActivityWatch</a>, also free.';
  } else if (/mac/i.test(platform)) {
    for (const b of buttons) { b.href = base + "autohours-macos-apple-silicon.zip"; b.textContent = "Download for Mac"; }
    note.innerHTML = 'Free, and experimental on Mac. For Apple silicon (M1 or newer); <a href="' + base + 'autohours-macos-intel.zip">older Intel Mac</a>. Works with <a href="https://activitywatch.net/">ActivityWatch</a>, also free.';
  }
})();
