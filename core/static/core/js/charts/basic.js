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
        // Consolidate to top 7 + Other
        const consolidated = utils.consolidateTopN(data, 7);
        const colors = consolidated.map((element, index) => {
            // Use gray for "Other"
            if (element._isOther) return 'hsl(0, 0%, 70%)';
            return utils.generateRandomColor(index, consolidated.length);
        });

        const chartData = {
            labels: consolidated.map(item => item.name),
            datasets: [{
                data: consolidated.map(item => item.total_time / 60),
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
        // Consolidate to top 7 + Other
        const consolidated = utils.consolidateTopN(data, 7);
        let colors = consolidated.map((element, index) => {
            // Use gray for "Other"
            if (element._isOther) return 'hsl(0, 0%, 70%)';
            return utils.generateRandomColor(index, consolidated.length);
        });

        const chartData = {
            labels: consolidated.map(item => item.name),
            datasets: [{
                label: 'Project Totals',
                data: consolidated.map(item => item.total_time / 60),
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

        // Group by project and calculate totals for ranking
        const projectGroups = sessionData.reduce((acc, item) => {
            if (!acc[item.projectName]) acc[item.projectName] = { sessions: [], totalTime: 0 };
            acc[item.projectName].sessions.push(item);
            acc[item.projectName].totalTime += item.y;
            return acc;
        }, {});

        // Sort projects by total time and take top 7
        const sortedProjects = Object.entries(projectGroups)
            .sort((a, b) => b[1].totalTime - a[1].totalTime);

        const topN = 7;
        const topProjects = sortedProjects.slice(0, topN);
        const otherProjects = sortedProjects.slice(topN);

        // Build final grouped data
        let groupedData = topProjects.map(([name, data]) => [name, data.sessions]);

        // Merge remaining projects into "Other"
        if (otherProjects.length > 0) {
            const otherSessions = otherProjects.flatMap(([_, data]) =>
                data.sessions.map(s => ({ ...s, projectName: `Other (${otherProjects.length})` }))
            );
            groupedData.push([`Other (${otherProjects.length})`, otherSessions]);
        }

        const projectColors = {};
        groupedData.forEach(([name], index) => {
            if (name.startsWith('Other (')) {
                projectColors[name] = 'hsl(0, 0%, 70%)';
            } else {
                projectColors[name] = utils.generateRandomColor(index, groupedData.length);
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
        const projectTotalTime = {};

        data.forEach(item => {
            const startTime = new Date(item.start_time);
            const endTime = new Date(item.end_time);
            const duration = (endTime - startTime) / (1000 * 60 * 60);
            const dateKey = startTime.toISOString().split('T')[0];
            const projectName = item.project;

            if (!dailyTotals[projectName]) dailyTotals[projectName] = {};
            if (!dailyTotals[projectName][dateKey]) dailyTotals[projectName][dateKey] = 0;
            dailyTotals[projectName][dateKey] += duration;

            // Track total time per project for ranking
            projectTotalTime[projectName] = (projectTotalTime[projectName] || 0) + duration;
        });

        // Sort projects by total time and identify top 7
        const topN = 7;
        const sortedProjects = Object.entries(projectTotalTime)
            .sort((a, b) => b[1] - a[1]);
        const topProjectNames = new Set(sortedProjects.slice(0, topN).map(([name]) => name));
        const otherProjects = sortedProjects.slice(topN);

        // Merge "other" projects into single entry
        if (otherProjects.length > 0) {
            const otherName = `Other (${otherProjects.length})`;
            dailyTotals[otherName] = {};
            otherProjects.forEach(([projectName]) => {
                Object.entries(dailyTotals[projectName]).forEach(([date, time]) => {
                    dailyTotals[otherName][date] = (dailyTotals[otherName][date] || 0) + time;
                });
                delete dailyTotals[projectName];
            });
        }

        const allDates = [...new Set(
            Object.values(dailyTotals).flatMap(proj => Object.keys(proj))
        )].sort();

        const projectNames = Object.keys(dailyTotals);
        // Sort so top projects come first, "Other" last
        projectNames.sort((a, b) => {
            if (a.startsWith('Other (')) return 1;
            if (b.startsWith('Other (')) return -1;
            return (projectTotalTime[b] || 0) - (projectTotalTime[a] || 0);
        });

        const datasets = projectNames.map((projectName, index) => {
            const isOther = projectName.startsWith('Other (');
            const color = isOther ? 'hsl(0, 0%, 70%)' : utils.generateRandomColor(index, projectNames.length);
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
