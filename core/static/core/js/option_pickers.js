/**
 * Option pickers — the search / pin / count behaviour behind every
 * multi-select filter (core/templates/core/partials/option_picker.html).
 *
 * One picker = [data-picker] wrapping a .picker-options well of .option-chip
 * labels. This script:
 *   - filters chips against the picker's search field,
 *   - keeps checked chips pinned to the front so a selection never scrolls
 *     out of sight (or gets filtered away and silently stays applied),
 *   - keeps a "N selected" button beside the label that clears the picker,
 *   - shows an empty state when a search matches nothing.
 *
 * A picker marked data-picker-meta="exclude-projects" additionally narrows
 * itself to the context and tags chosen elsewhere in the same form, using the
 * global EXCLUDE_PROJECT_META the page defines:
 *   { "<project_id>": { "ctx": <context_id|null>, "tags": [<tag_id>, ...] } }
 *
 * The commitment pages run their own dropdown logic over .commitment-rule-*
 * and deliberately do NOT carry data-picker, so the two never fight.
 */
(function () {
    "use strict";

    function chipsOf(picker) {
        return Array.prototype.slice.call(picker.querySelectorAll(".option-chip"));
    }

    function boxOf(chip) {
        return chip.querySelector('input[type="checkbox"]');
    }

    function labelOf(chip) {
        var el = chip.querySelector(".option-label");
        return (el ? el.textContent : chip.textContent).trim().toLowerCase();
    }

    /** Context / tag selections live outside the picker, in the same form. */
    function formScope(picker) {
        var form = picker.closest("form") || document;
        var ctxEl = form.querySelector('select[name="context"]');
        var ctx = ctxEl && ctxEl.value ? parseInt(ctxEl.value, 10) : NaN;
        var tags = [];
        Array.prototype.forEach.call(
            form.querySelectorAll('input[name="tags"]:checked'),
            function (el) {
                var id = parseInt(el.value, 10);
                if (!isNaN(id)) { tags.push(id); }
            }
        );
        return { ctx: isNaN(ctx) ? null : ctx, tags: tags };
    }

    function inScope(chip, picker) {
        if (picker.dataset.pickerMeta !== "exclude-projects") { return true; }
        if (typeof EXCLUDE_PROJECT_META === "undefined" || !EXCLUDE_PROJECT_META) { return true; }
        var box = boxOf(chip);
        var meta = box && EXCLUDE_PROJECT_META[box.value];
        if (!meta) { return true; }

        var scope = formScope(picker);
        if (scope.ctx !== null && meta.ctx !== scope.ctx) { return false; }
        if (scope.tags.length) {
            var tags = meta.tags || [];
            var hit = scope.tags.some(function (id) { return tags.indexOf(id) !== -1; });
            if (!hit) { return false; }
        }
        return true;
    }

    /** Checked chips first, original order preserved within each half. */
    function pin(well, chips) {
        var checked = chips.filter(function (c) { var b = boxOf(c); return b && b.checked; });
        if (!checked.length) { return; }
        var current = Array.prototype.slice.call(well.children);
        var wanted = checked.concat(chips.filter(function (c) { return checked.indexOf(c) === -1; }));
        var same = wanted.every(function (c, i) { return current[i] === c; });
        if (same) { return; }
        wanted.forEach(function (chip) { well.appendChild(chip); });
    }

    function refresh(picker) {
        var well = picker.querySelector(".picker-options");
        if (!well) { return; }

        var searchEl = picker.querySelector(".picker-search-input");
        var term = (searchEl && searchEl.value || "").trim().toLowerCase();
        var chips = chipsOf(picker);
        var shown = 0;
        var selected = 0;

        chips.forEach(function (chip) {
            var box = boxOf(chip);
            var checked = !!(box && box.checked);
            if (checked) { selected += 1; }

            // A checked option always stays visible: it is applied, so hiding
            // it would hide a filter the user cannot then see or undo.
            var visible = checked ||
                ((!term || labelOf(chip).indexOf(term) !== -1) && inScope(chip, picker));

            chip.hidden = !visible;
            if (visible) { shown += 1; }
        });

        pin(well, chips);

        var empty = picker.querySelector("[data-picker-empty]");
        if (empty) { empty.hidden = shown !== 0; }

        var count = (picker.closest(".field") || document).querySelector("[data-picker-count]");
        if (count) {
            count.hidden = selected === 0;
            count.textContent = selected + " selected · clear";
            count.setAttribute("aria-label", "Clear the " + selected + " selected options");
        }
    }

    function refreshAll() {
        Array.prototype.forEach.call(document.querySelectorAll("[data-picker]"), refresh);
    }

    function init() {
        var pickers = Array.prototype.slice.call(document.querySelectorAll("[data-picker]"));
        if (!pickers.length) { return; }

        pickers.forEach(function (picker) {
            var searchEl = picker.querySelector(".picker-search-input");
            if (searchEl) {
                searchEl.addEventListener("input", function () { refresh(picker); });
                // The picker lives inside a GET form; Enter should not submit
                // the whole filter sheet from a client-side search box.
                searchEl.addEventListener("keydown", function (ev) {
                    if (ev.key === "Enter") { ev.preventDefault(); }
                });
            }

            picker.addEventListener("change", function (ev) {
                if (ev.target.matches('input[type="checkbox"]')) { refresh(picker); }
            });

            var count = (picker.closest(".field") || document).querySelector("[data-picker-count]");
            if (count) {
                count.addEventListener("click", function () {
                    chipsOf(picker).forEach(function (chip) {
                        var box = boxOf(chip);
                        if (box) { box.checked = false; }
                    });
                    refresh(picker);
                });
            }
        });

        // Context and tag choices narrow the exclude-projects picker.
        document.addEventListener("change", function (ev) {
            if (ev.target.matches('select[name="context"], input[name="tags"]')) {
                refreshAll();
            }
        });

        refreshAll();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
}());
