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
        var term = $(this).val().toLowerCase();
        $(this).closest(".exclude-options").find(".exclude-option").each(function () {
            var label = $(this).find(".tag-label").text().toLowerCase();
            $(this).toggle(label.indexOf(term) !== -1);
        });
        // Re-apply context/tag filtering after text search
        filterExcludeOptions();
    });

    // --- React to context / tag changes ---
    // Context dropdown (select)
    $(document).on("change", "#context-filter, [name='context']", function () {
        filterExcludeOptions();
    });
    // Tag checkboxes
    $(document).on("change", "input[name='tags']", function () {
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
            var pid = $input.val();
            var meta = EXCLUDE_PROJECT_META[pid];

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

            // Uncheck hidden options so they aren't submitted
            if (!visible && $input.is(":checked")) {
                $input.prop("checked", false);
            }
        });
    }
});
