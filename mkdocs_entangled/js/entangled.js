document.addEventListener("click", function (e) {
  var link = e.target.closest("a.entangled-link");
  if (!link) return;
  var hash = link.hash;
  if (!hash) return;
  var target = document.getElementById(hash.slice(1));
  if (!target) return;
  e.preventDefault();
  e.stopPropagation();
  // The anchor <a id="..."> is invisible; scroll to the next visible sibling instead
  var scrollTarget = target.nextElementSibling || target;
  var offset = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue("--entangled-scroll-offset")) || 80;
  var top = scrollTarget.getBoundingClientRect().top + window.scrollY - offset;
  window.scrollTo({ top: top, behavior: "smooth" });
  history.pushState(null, "", hash);
}, true);
