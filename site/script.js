// Point the main download buttons at the right file for this computer. Phones, tablets and Linux get a note instead.
(() => {
  const base = "https://github.com/Gabriel-Dalton/autohours/releases/latest/download/";
  const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
  const agent = navigator.userAgent;
  // iPads report themselves as a Mac; touch points give them away.
  const tablet = /mac/i.test(platform) && navigator.maxTouchPoints > 1;
  const mobile = tablet || /iphone|ipad|ipod|android/i.test(platform + " " + agent) || (navigator.userAgentData && navigator.userAgentData.mobile);
  const buttons = [document.getElementById("download"), ...document.querySelectorAll("[data-download]")];
  const note = document.getElementById("download-note");
  const set = (href, label) => { for (const b of buttons) { b.href = href; b.textContent = label; } };
  if (mobile) {
    set("#all-downloads", "Get it for your computer");
    note.textContent = "autohours runs on Windows and Mac computers. Open this page on your computer to download it, free.";
  } else if (/win/i.test(platform)) {
    set(base + "autohours-windows.exe", "Download for Windows");
    note.innerHTML = 'Free. Also for <a href="#all-downloads">Mac</a>. Works with <a href="https://activitywatch.net/">ActivityWatch</a>, also free.';
  } else if (/mac/i.test(platform)) {
    set(base + "autohours-macos-apple-silicon.zip", "Download for Mac");
    note.innerHTML = 'Free, and experimental on Mac. For Apple silicon (M1 or newer); <a href="' + base + 'autohours-macos-intel.zip">older Intel Mac</a>. Works with <a href="https://activitywatch.net/">ActivityWatch</a>, also free.';
  } else if (/linux/i.test(platform)) {
    note.textContent = "autohours is for Windows and Mac. Linux is not supported.";
  }
})();
