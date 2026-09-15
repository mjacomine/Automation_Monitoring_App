/* ============================================================================
   nav-menu.js — behavior for the ported NavigationMenu component
   ----------------------------------------------------------------------------
   Vanilla, dependency-free replacement for Radix NavigationMenu. Enhances any
   element with [data-navmenu]:

     <nav class="navmenu" data-navmenu>
       <ul class="navmenu-list">
         <li class="navmenu-item">
           <button class="navmenu-trigger" aria-controls="PANEL_ID">Label …</button>
           <div class="navmenu-content" id="PANEL_ID" hidden> … </div>
         </li>
         <li class="navmenu-item"><a class="navmenu-link" href="…">Label</a></li>
       </ul>
     </nav>

   Behavior mirrors the original: hover-intent open on pointer devices, click to
   toggle (works for touch), keyboard operable (Enter/Space via the button,
   Escape to close and restore focus), outside-click to close, and only one
   panel open at a time. Respects prefers-reduced-motion. Items whose <li> has
   no .navmenu-content (plain links) are left alone.
   ========================================================================== */
(function () {
  "use strict";

  var OPEN_DELAY = 120;   // ms hover-intent before opening
  var CLOSE_DELAY = 160;  // ms grace before closing on mouseleave
  var EXIT_MS = 260;      // fallback for the panel exit transition
  var reduce = window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function initRoot(root) {
    var items = Array.prototype.slice.call(root.querySelectorAll(".navmenu-item"));
    var hoverable = window.matchMedia
      ? window.matchMedia("(hover: hover) and (pointer: fine)").matches : true;
    var openItem = null, openTimer = null, closeTimer = null;

    function panelOf(item) { return item.querySelector(".navmenu-content"); }
    function triggerOf(item) { return item.querySelector(".navmenu-trigger"); }

    function openPanel(item) {
      if (openItem === item) return;
      if (openItem) closePanel(openItem, true);
      var t = triggerOf(item), p = panelOf(item);
      if (!t || !p) return;
      openItem = item;
      t.setAttribute("aria-expanded", "true");
      p.hidden = false;
      if (reduce) {
        p.setAttribute("data-open", "true");
      } else {
        // Next frame so the transition runs from the hidden starting state.
        requestAnimationFrame(function () { p.setAttribute("data-open", "true"); });
      }
    }

    function closePanel(item, immediate) {
      var t = triggerOf(item), p = panelOf(item);
      if (!t || !p) return;
      t.setAttribute("aria-expanded", "false");
      p.setAttribute("data-open", "false");
      if (openItem === item) openItem = null;
      if (reduce || immediate) {
        p.hidden = true;
        return;
      }
      var done = function (e) {
        if (e.target !== p) return;
        p.hidden = true;
        p.removeEventListener("transitionend", done);
      };
      p.addEventListener("transitionend", done);
      // Fallback in case transitionend doesn't fire (e.g. display quirks).
      setTimeout(function () {
        if (p.getAttribute("data-open") === "false") p.hidden = true;
      }, EXIT_MS);
    }

    function toggle(item) {
      if (openItem === item) closePanel(item); else openPanel(item);
    }

    items.forEach(function (item) {
      var t = triggerOf(item), p = panelOf(item);
      if (!t || !p) return;  // plain-link item — nothing to wire

      t.setAttribute("aria-haspopup", "true");
      t.setAttribute("aria-expanded", "false");

      t.addEventListener("click", function (e) { e.preventDefault(); toggle(item); });
      t.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && openItem === item) { closePanel(item); t.focus(); }
      });
      p.addEventListener("keydown", function (e) {
        if (e.key === "Escape") { closePanel(item); t.focus(); }
      });

      if (hoverable) {
        item.addEventListener("mouseenter", function () {
          clearTimeout(closeTimer);
          openTimer = setTimeout(function () { openPanel(item); }, OPEN_DELAY);
        });
        item.addEventListener("mouseleave", function () {
          clearTimeout(openTimer);
          closeTimer = setTimeout(function () { closePanel(item); }, CLOSE_DELAY);
        });
      }

      // Selecting a link inside the panel closes it immediately.
      p.addEventListener("click", function (e) {
        if (e.target.closest("a")) closePanel(item, true);
      });
    });

    document.addEventListener("click", function (e) {
      if (openItem && !root.contains(e.target)) closePanel(openItem, true);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && openItem) {
        var t = triggerOf(openItem);
        closePanel(openItem);
        if (t) t.focus();
      }
    });
  }

  function initAll() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-navmenu]"), initRoot);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();
