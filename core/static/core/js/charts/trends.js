/**
 * Trend Charts Module
 * Stacked Area and Cumulative Line charts
 */

(function() {
    const utils = window.AutumnCharts.utils;

    // ========================================================================
    // Stacked Area Chart
    // ========================================================================

    function stacked_area_chart(data, ctx) {
        const dailyTotals = {};

        data.forEach(item => {
            const startTime = new Date(item.start_time);
            const endTime = new Date(item.end_time);
            const duration = (endTime - startTime) / (1000 * 60 * 60);
            const dateKey = startTime.toISOString().split('T')[0];
            const projectName = item.project;

            if (!dailyTotals[projectName]) dailyTotals[projectName] = {};
            if (!dailyTotals[projectName][dateKey]) dailyTotals[projectName][dateKey] = 0;
            dailyTotals[projectName][dateKey] += duration;
        });

        // Get all unique dates and sort them
        const allDates = [...new Set(
            Object.values(dailyTotals).flatMap(proj => Object.keys(proj))
        )].sort();

        const projectNames = Object.keys(dailyTotals).sort();
        const datasets = projectNames.map((projectName, index) => {
            const color = utils.generateRandomColor(index, projectNames.length);
            const projectData = dailyTotals[projectName];

            // Include all dates (with 0 for missing days) for proper stacking
            const dataPoints = allDates.map(date => ({
                x: new Date(date),
                y: projectData[date] || 0
            }));

            return {
                label: projectName,
                data: dataPoints,
                borderColor: color,
                backgroundColor: color.replace('hsl', 'hsla').replace(')', ', 0.6)'),
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                pointHoverRadius: 4
            };
        });

        utils.clearChart(ctx);

        const dates = data.map(item => new Date(item.start_time));
        const minDate = new Date(Math.min(...dates));
        const maxDate = new Date(Math.max(...dates));
        const chartUnit = utils.getChartUnit(maxDate, minDate);

        new Chart(ctx, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true,
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: chartUnit },
                        title: { display: true, text: 'Date' }
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        title: { display: true, text: 'Hours' }
                    }
                },
                plugins: {
                    title: {
                        display: true,
                        text: 'Daily Time by Project (Stacked)'
                    },
                    tooltip: {
                        mode: 'index',
                        callbacks: {
                            label(context) {
                                const v = context.parsed.y.toFixed(2);
                                return `${context.dataset.label}: ${v} hours`;
                            }
                        }
                    },
                    filler: {
                        propagate: true
                    }
                },
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false
                }
            }
        });
    }

    function stacked_area_subprojects_chart(data, ctx) {
        const dailyTotals = {};

        data.forEach(item => {
            const startTime = new Date(item.start_time);
            const endTime = new Date(item.end_time);
            const duration = (endTime - startTime) / (1000 * 60 * 60);
            const dateKey = startTime.toISOString().split('T')[0];

            const subprojects = (item.subprojects || []).length
                ? item.subprojects.map(sp => sp.name || sp)
                : ['no subproject'];

            subprojects.forEach(spName => {
                if (!dailyTotals[spName]) dailyTotals[spName] = {};
                if (!dailyTotals[spName][dateKey]) dailyTotals[spName][dateKey] = 0;
                dailyTotals[spName][dateKey] += duration;
            });
        });

        const allDates = [...new Set(
            Object.values(dailyTotals).flatMap(sp => Object.keys(sp))
        )].sort();

        const subprojectNames = Object.keys(dailyTotals).sort();
        const datasets = subprojectNames.map((spName, index) => {
            const color = utils.generateRandomColor(index, subprojectNames.length);
            const spData = dailyTotals[spName];

            const dataPoints = allDates.map(date => ({
                x: new Date(date),
                y: spData[date] || 0
            }));

            return {
                label: spName,
                data: dataPoints,
                borderColor: color,
                backgroundColor: color.replace('hsl', 'hsla').replace(')', ', 0.6)'),
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                pointHoverRadius: 4
            };
        });

        utils.clearChart(ctx);

        const dates = data.map(item => new Date(item.start_time));
        const minDate = new Date(Math.min(...dates));
        const maxDate = new Date(Math.max(...dates));
        const chartUnit = utils.getChartUnit(maxDate, minDate);

        new Chart(ctx, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true,
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: chartUnit },
                        title: { display: true, text: 'Date' }
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        title: { display: true, text: 'Hours' }
                    }
                },
                plugins: {
                    title: {
                        display: true,
                        text: 'Daily Time by Subproject (Stacked)'
                    },
                    tooltip: {
                        mode: 'index',
                        callbacks: {
                            label(context) {
                                const v = context.parsed.y.toFixed(2);
                                return `${context.dataset.label}: ${v} hours`;
                            }
                        }
                    }
                },
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false
                }
            }
        });
    }

    // ========================================================================
    // Cumulative Line Chart
    // ========================================================================

    function cumulative_line_chart(data, ctx) {
        // Sort sessions by start time
        const sortedSessions = [...data].sort((a, b) =>
            new Date(a.start_time) - new Date(b.start_time)
        );

        // Calculate daily totals first
        const dailyTotals = {};
        sortedSessions.forEach(item => {
            const startTime = new Date(item.start_time);
            const endTime = new Date(item.end_time);
            const duration = (endTime - startTime) / (1000 * 60 * 60);
            const dateKey = startTime.toISOString().split('T')[0];

            if (!dailyTotals[dateKey]) dailyTotals[dateKey] = 0;
            dailyTotals[dateKey] += duration;
        });

        // Sort dates and calculate cumulative
        const sortedDates = Object.keys(dailyTotals).sort();
        let cumulative = 0;
        const dataPoints = sortedDates.map(date => {
            cumulative += dailyTotals[date];
            return {
                x: new Date(date),
                y: cumulative,
                daily: dailyTotals[date]
            };
        });

        utils.clearChart(ctx);

        const minDate = new Date(sortedDates[0]);
        const maxDate = new Date(sortedDates[sortedDates.length - 1]);
        const chartUnit = utils.getChartUnit(maxDate, minDate);

        new Chart(ctx, {
            type: 'line',
            data: {
                datasets: [{
                    label: 'Cumulative Hours',
                    data: dataPoints,
                    borderColor: 'hsl(210, 70%, 55%)',
                    backgroundColor: 'hsla(210, 70%, 55%, 0.2)',
                    fill: true,
                    tension: 0.2,
                    pointRadius: 3,
                    pointHoverRadius: 6
                }]
            },
            options: {
                responsive: true,
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: chartUnit },
                        title: { display: true, text: 'Date' }
                    },
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: 'Total Hours' }
                    }
                },
                plugins: {
                    title: {
                        display: true,
                        text: 'Cumulative Time Tracked'
                    },
                    tooltip: {
                        callbacks: {
                            label(context) {
                                const point = context.raw;
                                return [
                                    `Total: ${point.y.toFixed(1)} hours`,
                                    `This day: +${point.daily.toFixed(2)} hours`
                                ];
                            }
                        }
                    }
                }
            }
        });
    }

    // ========================================================================
    // Register charts
    // ========================================================================

    window.AutumnCharts.registerAll({
        stacked_area: stacked_area_chart,
        stacked_area_subprojects: stacked_area_subprojects_chart,
        cumulative: cumulative_line_chart
    });

})();
