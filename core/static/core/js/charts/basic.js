/**
 * Basic Charts Module
 * Pie, Bar, Line, Scatter charts using standard Chart.js
 */

(function() {
    const utils = window.AutumnCharts.utils;

    // ========================================================================
    // Pie / Donut Chart
    // ========================================================================

    function pie_chart(data, ctx) {
        const colors = data.map((element, index) => utils.generateRandomColor(index, data.length));

        const chartData = {
            labels: data.map(item => item.name),
            datasets: [{
                data: data.map(item => item.total_time / 60),
                backgroundColor: colors,
                borderWidth: 0.5
            }]
        };

        utils.clearChart(ctx);

        new Chart(ctx, {
            type: 'doughnut',
            data: chartData,
            options: {
                responsive: true,
                plugins: {
                    title: {
                        display: true,
                        text: 'Project Time Distribution'
                    },
                    legend: {
                        position: 'top',
                    }
                },
                cutout: '40%'
            }
        });
    }

    // ========================================================================
    // Bar Chart
    // ========================================================================

    function bar_graph(data, ctx) {
        let colors = data.map((element, index) => utils.generateRandomColor(index, data.length));

        const chartData = {
            labels: data.map(item => item.name),
            datasets: [{
                label: 'Project Totals',
                data: data.map(item => item.total_time / 60),
                backgroundColor: colors,
                borderWidth: 0.5
            }]
        };

        utils.clearChart(ctx);

        new Chart(ctx, {
            type: 'bar',
            data: chartData,
            options: {
                responsive: true,
                indexAxis: 'y',
            }
        });
    }

    // ========================================================================
    // Scatter Chart
    // ========================================================================

    function scatter_graph(data, ctx) {
        const sessionData = data.map(item => {
            const startTime = new Date(item.start_time);
            const endTime = new Date(item.end_time);
            const duration = (endTime - startTime) / (1000 * 60 * 60);

            return {
                x: endTime,
                y: duration,
                projectName: item.project
            };
        });

        const groupedData = Object.entries(
            sessionData.reduce((acc, item) => {
                if (!acc[item.projectName]) acc[item.projectName] = [];
                acc[item.projectName].push(item);
                return acc;
            }, {})
        );

        groupedData.sort((a, b) => a[0].localeCompare(b[0]));

        const projectColors = {};
        groupedData.forEach((item, index) => {
            if (!projectColors[item[0]]) {
                projectColors[item[0]] = utils.generateRandomColor(index, groupedData.length);
            }
        });

        const chartData = {
            datasets: groupedData.map(([projectName, data]) => ({
                label: projectName,
                data: data,
                backgroundColor: projectColors[projectName],
                pointHoverRadius: 6,
                pointStyle: 'rect',
                pointRotation: 45,
            }))
        };

        utils.clearChart(ctx);

        let endDate = new Date(sessionData[0].x);
        let startDate = new Date(sessionData[sessionData.length - 1].x);
        let chartUnit = utils.getChartUnit(endDate, startDate);

        new Chart(ctx, {
            type: 'scatter',
            data: chartData,
            options: {
                responsive: true,
                scales: {
                    x: {
                        type: 'time',
                        time: { unit: chartUnit },
                        title: { display: true, text: 'Date' }
                    },
                    y: {
                        title: { display: true, text: 'Duration (hours)' },
                        beginAtZero: true
                    }
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) label += ': ';
                                if (context.parsed.y !== null) {
                                    label += context.parsed.y.toFixed(2) + ' hours';
                                }
                                return label;
                            }
                        }
                    }
                }
            }
        });
    }

    function scatter_subproject_graph(data, ctx) {
        const pts = [];
        data.forEach(s => {
            const start = new Date(s.start_time);
            const end = new Date(s.end_time);
            const dur = (end - start) / (1000 * 60 * 60);
            if ((s.subprojects || []).length) {
                (s.subprojects).forEach(sp => {
                    const name = sp.name || sp;
                    pts.push({ x: end, y: dur, projectName: name });
                });
            } else {
                pts.push({ x: end, y: dur, projectName: "no subproject" });
            }
        });

        const grouped = Object.entries(
            pts.reduce((acc, p) => {
                (acc[p.projectName] = acc[p.projectName] || []).push(p);
                return acc;
            }, {})
        ).sort((a, b) => a[0].localeCompare(b[0]));

        const colors = {};
        grouped.forEach(([name], i) => {
            colors[name] = utils.generateRandomColor(i, grouped.length);
        });

        const datasets = grouped.map(([name, arr]) => ({
            label: name,
            data: arr,
            backgroundColor: colors[name],
            pointStyle: 'rect',
            pointRotation: 45,
            pointHoverRadius: 6
        }));

        utils.clearChart(ctx);

        const allX = pts.map(p => p.x).sort((a, b) => a - b);
        const unit = utils.getChartUnit(allX[allX.length - 1], allX[0]);

        new Chart(ctx, {
            type: 'scatter',
            data: { datasets },
            options: {
                responsive: true,
                scales: {
                    x: {
                        type: 'time',
                        time: { unit },
                        title: { display: true, text: 'Date' }
                    },
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: 'Duration (hours)' }
                    }
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label(ctx) {
                                const v = ctx.parsed.y.toFixed(2);
                                return `${ctx.dataset.label}: ${v} h`;
                            }
                        }
                    }
                }
            }
        });
    }

    // ========================================================================
    // Line Chart
    // ========================================================================

    function line_graph(data, ctx) {
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

        const allDates = [...new Set(
            Object.values(dailyTotals).flatMap(proj => Object.keys(proj))
        )].sort();

        const projectNames = Object.keys(dailyTotals).sort();
        const datasets = projectNames.map((projectName, index) => {
            const color = utils.generateRandomColor(index, projectNames.length);
            const projectData = dailyTotals[projectName];

            const dataPoints = allDates.map(date => ({
                x: new Date(date),
                y: projectData[date] || 0
            })).filter(point => point.y > 0);

            return {
                label: projectName,
                data: dataPoints,
                borderColor: color,
                backgroundColor: color,
                fill: false,
                tension: 0.1,
                pointRadius: 4,
                pointHoverRadius: 6
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
                        beginAtZero: true,
                        title: { display: true, text: 'Duration (hours)' }
                    }
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label(context) {
                                const v = context.parsed.y.toFixed(2);
                                return `${context.dataset.label}: ${v} hours`;
                            }
                        }
                    }
                }
            }
        });
    }

    function line_subproject_graph(data, ctx) {
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
            })).filter(point => point.y > 0);

            return {
                label: spName,
                data: dataPoints,
                borderColor: color,
                backgroundColor: color,
                fill: false,
                tension: 0.1,
                pointRadius: 4,
                pointHoverRadius: 6
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
                        beginAtZero: true,
                        title: { display: true, text: 'Duration (hours)' }
                    }
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label(context) {
                                const v = context.parsed.y.toFixed(2);
                                return `${context.dataset.label}: ${v} hours`;
                            }
                        }
                    }
                }
            }
        });
    }

    // ========================================================================
    // Status Donut Chart
    // ========================================================================

    function status_donut_chart(data, ctx) {
        // Fixed colors for each status
        const statusColors = {
            'active': 'hsl(120, 70%, 50%)',    // Green
            'paused': 'hsl(45, 90%, 55%)',     // Yellow/Orange
            'complete': 'hsl(210, 70%, 55%)',  // Blue
            'archived': 'hsl(0, 0%, 60%)'      // Gray
        };

        const statusOrder = ['active', 'paused', 'complete', 'archived'];
        const sortedData = statusOrder
            .map(status => data.find(d => d.status === status))
            .filter(d => d);

        const chartData = {
            labels: sortedData.map(item => `${item.status} (${item.count})`),
            datasets: [{
                data: sortedData.map(item => item.total_time / 60),
                backgroundColor: sortedData.map(item => statusColors[item.status] || '#999'),
                borderWidth: 1
            }]
        };

        utils.clearChart(ctx);

        new Chart(ctx, {
            type: 'doughnut',
            data: chartData,
            options: {
                responsive: true,
                plugins: {
                    title: {
                        display: true,
                        text: 'Time by Project Status'
                    },
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const hours = context.parsed.toFixed(1);
                                return `${context.label}: ${hours} hours`;
                            }
                        }
                    }
                },
                cutout: '50%'
            }
        });
    }

    // ========================================================================
    // Context Comparison Bar Chart
    // ========================================================================

    function context_bar_chart(data, ctx) {
        // Sort by total time descending
        const sortedData = [...data].sort((a, b) => b.total_time - a.total_time);
        const colors = sortedData.map((_, index) => utils.generateRandomColor(index, sortedData.length));

        const chartData = {
            labels: sortedData.map(item => item.name),
            datasets: [{
                label: 'Hours by Context',
                data: sortedData.map(item => item.total_time / 60),
                backgroundColor: colors,
                borderWidth: 1
            }]
        };

        utils.clearChart(ctx);

        new Chart(ctx, {
            type: 'bar',
            data: chartData,
            options: {
                responsive: true,
                indexAxis: 'y',
                plugins: {
                    title: {
                        display: true,
                        text: 'Time by Context'
                    },
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `${context.parsed.x.toFixed(1)} hours`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        title: { display: true, text: 'Hours' },
                        beginAtZero: true
                    }
                }
            }
        });
    }

    // ========================================================================
    // Register all charts
    // ========================================================================

    window.AutumnCharts.registerAll({
        pie: pie_chart,
        bar: bar_graph,
        scatter: scatter_graph,
        scatter_subprojects: scatter_subproject_graph,
        line: line_graph,
        line_subprojects: line_subproject_graph,
        status: status_donut_chart,
        context: context_bar_chart
    });

})();
