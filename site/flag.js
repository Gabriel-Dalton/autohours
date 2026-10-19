// Runs before the page paints, so the hero starts hidden instead of flashing its finished state.
document.documentElement.classList.add("js");
if (!matchMedia("(prefers-reduced-motion: reduce)").matches) document.documentElement.classList.add("anim");
setTimeout(() => { if (!document.querySelector("#hero-demo.ready")) document.documentElement.classList.remove("anim"); }, 3000);
