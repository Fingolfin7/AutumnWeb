/**
 * Exclude-projects dropdown: client-side search + reactive filtering
 * based on the current context and tag selections.
 *
 * Expects a global `EXCLUDE_PROJECT_META` object:
 *   { "<project_id>": { "ctx": <context_id|null>, "tags": [<tag_id>, ...] }, ... }
 */
$(document).ready(function () {
    // --- Text search within the dropdown ---
    $(".exclude-search-input").on("input", function () {
        filterExcludeOptions();
    });

    // --- React to context / tag changes ---
    $(document).on("change", "#context-filter, [name='context']", function () {
        filterExcludeOptions();
    });
    $(document).on("change", "input[name='tags']", function () {
        filterExcludeOptions();
    });

    // --- React to checkbox changes (re-pin selected items) ---
    $(document).on("change", "input[name='exclude_projects']", function () {
        filterExcludeOptions();
    });

    // Initial filter on page load (in case context/tags are pre-selected)
    filterExcludeOptions();

    function filterExcludeOptions() {
        if (typeof EXCLUDE_PROJECT_META === "undefined") return;

        // Read selected context
        var ctxVal = $("#context-filter").val() || $("select[name='context']").val() || "";
        var selectedCtx = ctxVal ? parseInt(ctxVal, 10) : null;
        if (isNaN(selectedCtx)) selectedCtx = null;

        // Read selected tag IDs
        var selectedTags = [];
        $("input[name='tags']:checked").each(function () {
            var v = parseInt($(this).val(), 10);
            if (!isNaN(v)) selectedTags.push(v);
        });

        // Read current text search term
        var searchTerm = ($(".exclude-search-input").val() || "").toLowerCase();

        $(".exclude-option").each(function () {
            var $opt = $(this);
            var $input = $opt.find("input[type='checkbox']");
            var isChecked = $input.is(":checked");
            var pid = $input.val();
            var meta = EXCLUDE_PROJECT_META[pid];

            // Checked items are always visible (pinned)
            if (isChecked) {
                $opt.show();
                return;
            }

            var visible = true;

            // Text search filter
            if (searchTerm) {
                var label = $opt.find(".tag-label").text().toLowerCase();
                if (label.indexOf(searchTerm) === -1) visible = false;
            }

            // Context filter: hide if a context is selected and project doesn't match
            if (visible && selectedCtx !== null && meta) {
                if (meta.ctx !== selectedCtx) visible = false;
            }

            // Tag filter: hide if tags are selected and project has none of them
            if (visible && selectedTags.length > 0 && meta) {
                var hasAny = selectedTags.some(function (tid) {
                    return meta.tags.indexOf(tid) !== -1;
                });
                if (!hasAny) visible = false;
            }

            $opt.toggle(visible);
        });

        // Pin checked items to the top of the options list
        $(".exclude-options").each(function () {
            var $container = $(this);
            var $checked = $container.find(".exclude-option").filter(function () {
                return $(this).find("input[type='checkbox']").is(":checked");
            });
            // Move each checked option right after the search input
            // (reverse order to preserve original relative order)
            var $anchor = $container.find(".exclude-search-input");
            $checked.get().reverse().forEach(function (el) {
                $anchor.after(el);
            });
        });
    }
});
