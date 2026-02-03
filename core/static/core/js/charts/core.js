/**
 * Charts Core Module
 * Shared utilities, data fetching, and render orchestration
 */

// Global chart function registry - modules register their charts here
window.AutumnCharts = window.AutumnCharts || {
    chartFns: {},
    register: function(name, fn) {
        this.chartFns[name] = fn;
    },
    registerAll: function(charts) {
        Object.assign(this.chartFns, charts);
    }
};

// ============================================================================
// Utility Functions
// ============================================================================

function generateRandomColor(element_position, element_count) {
    let hue = (element_position * 360) / element_count;
    return `hsl(${hue}, 100%, 70%)`;
}

function generateColorWithSaturation(element_position, element_count, saturation = 100, lightness = 70) {
    let hue = (element_position * 360) / element_count;
    return `hsl(${hue}, ${saturation}%, ${lightness}%)`;
}

function fillDates(minDate, maxDate) {
    const dateList = [];
    for (let date = new Date(minDate); date <= maxDate; date.setDate(date.getDate() + 1)) {
        dateList.push(new Date(date));
    }
    return dateList;
}

function getChartUnit(endDate, startDate, defaultUnit = 'week') {
    const msPerDay = 24 * 60 * 60 * 1000;
    const daysDifference = Math.round((endDate - startDate) / msPerDay);
    const monthsDifference = (endDate.getFullYear() - startDate.getFullYear()) * 12 + endDate.getMonth() - startDate.getMonth();

    if (daysDifference <= 21) {
        return 'day';
    } else if (daysDifference <= 90) {
        return 'week';
    } else if (monthsDifference <= 18) {
        return 'month';
    } else {
        return 'year';
    }
}

function format_date(date) {
    let month = date.getMonth() + 1;
    let day = date.getDate();
    let year = date.getFullYear();
    return `${month}-${day}-${year}`;
}

function countWeekdays(startDate, endDate) {
    const counts = Array(7).fill(0);
    const d = new Date(startDate);
    while (d <= endDate) {
        counts[d.getDay()] += 1;
        d.setDate(d.getDate() + 1);
    }
    return counts;
}

function clearChart(ctx) {
    try {
        const existing = Chart.getChart(ctx);
        if (existing) existing.destroy();
    } catch (e) {
        // ignore
    }
}

function formatDuration(hours) {
    if (hours < 1) {
        return `${Math.round(hours * 60)}m`;
    } else if (hours < 24) {
        return `${hours.toFixed(1)}h`;
    } else {
        const days = Math.floor(hours / 24);
        const remainingHours = hours % 24;
        return `${days}d ${remainingHours.toFixed(0)}h`;
    }
}

// ============================================================================
// Data Fetching
// ============================================================================

function get_project_data(type, start_date = "", end_date = "", project_name = "", context_id = "", tag_ids = []) {
    let url = "";

    const wantSubprojects = project_name && (type === 'pie' || type === 'bar');

    // Map chart types to their data sources
    const sessionBasedCharts = ['scatter', 'calendar', 'heatmap', 'line', 'stacked_area', 'cumulative', 'histogram'];
    const hierarchyCharts = ['treemap'];
    const contextCharts = ['context'];
    const statusCharts = ['status'];
    const tagCharts = ['bubble'];
    const radarCharts = ['radar'];

    if (wantSubprojects) {
        url = $('#subprojects_tally_link').val();
    } else if (sessionBasedCharts.includes(type)) {
        url = $('#sessions_link').val();
    } else if (type === 'wordcloud') {
        url = $('#raw_sessions_link').val();
    } else if (hierarchyCharts.includes(type)) {
        url = $('#hierarchy_link').val();
    } else if (contextCharts.includes(type)) {
        url = $('#context_tally_link').val();
    } else if (statusCharts.includes(type)) {
        url = $('#status_tally_link').val();
    } else if (tagCharts.includes(type)) {
        url = $('#tags_tally_link').val();
    } else if (radarCharts.includes(type)) {
        // Radar uses project stats endpoint
        url = $('#projects_stats_link').val();
    } else {
        url = $('#projects_link').val();
    }

    // Build query string safely
    const qs = new URLSearchParams();
    if (project_name) qs.set('project_name', project_name);
    if (start_date) qs.set('start_date', start_date);
    if (end_date) qs.set('end_date', end_date);
    if (context_id) qs.set('context', context_id);
    if (Array.isArray(tag_ids) && tag_ids.length) {
        tag_ids.forEach(t => qs.append('tags', t));
    }

    const query = qs.toString();
    if (query) url += '?' + query;

    console.log('Fetching chart data:', url);

    return new Promise((resolve, reject) => {
        $.ajax({
            url: url,
            type: 'GET',
            dataType: 'json',
            success: function(data) {
                resolve(data);
            },
            error: function(error) {
                reject(error);
            }
        });
    });
}

// ============================================================================
// UI Helpers
// ============================================================================

let $loading, $empty, $canvasContainer;

function initUIElements() {
    $loading = $('#chart-loading');
    $empty = $('#chart-empty');
    $canvasContainer = $('#canvas_container');
}

function showLoading(message = 'Loading chart…') {
    if (!$loading || !$loading.length) return;
    $loading.find('.loading-text').text(message);
    $loading.attr('aria-busy', 'true').show();
}

function hideLoading() {
    if (!$loading || !$loading.length) return;
    $loading.attr('aria-busy', 'false').hide();
}

function showEmpty() {
    if ($empty && $empty.length) $empty.show();
    if ($canvasContainer && $canvasContainer.length) $canvasContainer.hide();
}

function hideEmpty() {
    if ($empty && $empty.length) $empty.hide();
    if ($canvasContainer && $canvasContainer.length) $canvasContainer.show();
}

// ============================================================================
// Main Render Orchestration
// ============================================================================

function render() {
    showLoading('Loading chart…');

    let selectType = $('#chart_type');
    let type = selectType.val();
    let canvasCtx = $('#chart')[0].getContext('2d');

    let start_date = $('#start_date').val();
    let end_date = $('#end_date').val();

    start_date = start_date ? format_date(new Date(start_date)) : "";
    end_date = end_date ? format_date(new Date(end_date)) : "";

    let project_name = ($('#project-search').val() || '').trim();

    let context_id = String($('#context-filter').val() || '').trim();
    if (!context_id) context_id = '';

    let $tagInputs = $('#tag-filter input[type="checkbox"]:checked');
    if (!$tagInputs.length) {
        $tagInputs = $('input[type="checkbox"][name="tags"]:checked');
    }
    const tag_ids = $tagInputs
        .map(function() { return String($(this).val()); })
        .get()
        .filter(v => v && v !== 'on');

    get_project_data(type, start_date, end_date, project_name, context_id, tag_ids)
        .then(data => {
            // Handle empty data
            if (!data || (Array.isArray(data) && !data.length)) {
                clearChart(canvasCtx);
                showEmpty();
                return;
            }

            hideEmpty();

            // Handle subproject variants
            if (project_name && type === 'scatter') {
                type = 'scatter_subprojects';
            }
            if (project_name && type === 'line') {
                type = 'line_subprojects';
            }
            if (project_name && type === 'stacked_area') {
                type = 'stacked_area_subprojects';
            }

            const chartFns = window.AutumnCharts.chartFns;

            if (!chartFns[type]) {
                console.error('Unknown chart type:', type);
                showEmpty();
                return;
            }

            // Special handling for wordcloud (needs canvas ID)
            if (type === 'wordcloud') {
                chartFns[type](data, canvasCtx, "#chart");
            } else {
                chartFns[type](data, canvasCtx);
            }
        })
        .catch(err => {
            console.error('Chart error:', err);
            try { clearChart(canvasCtx); } catch(e) {}
            showEmpty();
        })
        .finally(() => {
            requestAnimationFrame(() => hideLoading());
        });
}

// ============================================================================
// Initialization
// ============================================================================

$(document).ready(function() {
    initUIElements();

    let selectType = $('#chart_type');
    let draw = $('#draw');

    // Persist chart type from server-rendered data attribute
    const preselectedType = selectType.data('selected');
    if (preselectedType) {
        selectType.val(preselectedType);
    }

    // Set default dates
    let current_date = new Date();
    if (!$('#start_date').val()) {
        $('#start_date').val(new Date(current_date.getFullYear(), current_date.getMonth(), 1).toISOString().split('T')[0]);
    }
    if (!$('#end_date').val()) {
        $('#end_date').val(new Date().toISOString().split('T')[0]);
    }

    // Initial draw
    render();
    draw.on('click', render);
});

// Export utilities for other modules
window.AutumnCharts.utils = {
    generateRandomColor,
    generateColorWithSaturation,
    fillDates,
    getChartUnit,
    format_date,
    countWeekdays,
    clearChart,
    formatDuration
};
