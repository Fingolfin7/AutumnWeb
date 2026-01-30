/**
 * Analysis Charts Module
 * Session Histogram, Radar, and Tag Bubble charts
 */

(function() {
    const utils = window.AutumnCharts.utils;

    // ========================================================================
    // Session Duration Histogram
    // ========================================================================

    function session_histogram(data, ctx) {
        // Define duration buckets (in hours)
        const buckets = [
            { label: '0-15m', min: 0, max: 0.25 },
            { label: '15-30m', min: 0.25, max: 0.5 },
            { label: '30-60m', min: 0.5, max: 1 },
            { label: '1-2h', min: 1, max: 2 },
            { label: '2-4h', min: 2, max: 4 },
            { label: '4-8h', min: 4, max: 8 },
            { label: '8h+', min: 8, max: Infinity }
        ];

        // Count sessions in each bucket
        const counts = buckets.map(() => 0);

        data.forEach(item => {
            const startTime = new Date(item.start_time);
            const endTime = new Date(item.end_time);
            const duration = (endTime - startTime) / (1000 * 60 * 60); // hours

            for (let i = 0; i < buckets.length; i++) {
                if (duration >= buckets[i].min && duration < buckets[i].max) {
                    counts[i]++;
                    break;
                }
            }
        });

        // Generate gradient colors from short (cool) to long (warm)
        const colors = buckets.map((_, i) => {
            const hue = 200 - (i * 30); // Blue to red
            return `hsl(${Math.max(0, hue)}, 70%, 55%)`;
        });

        utils.clearChart(ctx);

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: buckets.map(b => b.label),
                datasets: [{
                    label: 'Number of Sessions',
                    data: counts,
                    backgroundColor: colors,
                    borderWidth: 1,
                    borderColor: colors.map(c => c.replace('55%', '45%'))
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    title: {
                        display: true,
                        text: 'Session Duration Distribution'
                    },
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                const count = ctx.parsed.y;
                                const total = counts.reduce((a, b) => a + b, 0);
                                const pct = total > 0 ? ((count / total) * 100).toFixed(1) : 0;
                                return `${count} sessions (${pct}%)`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        title: { display: true, text: 'Session Duration' }
                    },
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: 'Number of Sessions' },
                        ticks: {
                            stepSize: 1,
                            callback: function(value) {
                                if (Number.isInteger(value)) return value;
                            }
                        }
                    }
                }
            }
        });
    }

    // ========================================================================
    // Radar Chart (Multi-dimensional project comparison)
    // ========================================================================

    function radar_chart(data, ctx) {
        // Get top N projects by total time
        const topN = 6;
        const sortedProjects = [...data]
            .filter(p => p.total_time > 0)
            .sort((a, b) => b.total_time - a.total_time)
            .slice(0, topN);

        if (sortedProjects.length === 0) {
            utils.clearChart(ctx);
            return;
        }

        // Calculate metrics for normalization
        const metrics = sortedProjects.map(p => ({
            name: p.name,
            totalTime: p.total_time / 60, // hours
            sessionCount: p.session_count || 0,
            avgSessionLength: p.session_count > 0 ? (p.total_time / 60) / p.session_count : 0,
            subprojectCount: p.subproject_count || 0,
            // Recency: days since last updated (lower is better, so we invert)
            recency: p.days_since_update !== undefined ? Math.max(0, 30 - p.days_since_update) : 15
        }));

        // Find max values for normalization
        const maxValues = {
            totalTime: Math.max(...metrics.map(m => m.totalTime), 1),
            sessionCount: Math.max(...metrics.map(m => m.sessionCount), 1),
            avgSessionLength: Math.max(...metrics.map(m => m.avgSessionLength), 1),
            subprojectCount: Math.max(...metrics.map(m => m.subprojectCount), 1),
            recency: 30
        };

        // Normalize to 0-100 scale
        const datasets = metrics.map((m, i) => ({
            label: m.name,
            data: [
                (m.totalTime / maxValues.totalTime) * 100,
                (m.sessionCount / maxValues.sessionCount) * 100,
                (m.avgSessionLength / maxValues.avgSessionLength) * 100,
                (m.subprojectCount / maxValues.subprojectCount) * 100,
                (m.recency / maxValues.recency) * 100
            ],
            borderColor: utils.generateRandomColor(i, metrics.length),
            backgroundColor: utils.generateRandomColor(i, metrics.length).replace('70%)', '70%, 0.2)'),
            borderWidth: 2,
            pointBackgroundColor: utils.generateRandomColor(i, metrics.length)
        }));

        utils.clearChart(ctx);

        new Chart(ctx, {
            type: 'radar',
            data: {
                labels: ['Total Time', 'Sessions', 'Avg Length', 'Subprojects', 'Recency'],
                datasets: datasets
            },
            options: {
                responsive: true,
                plugins: {
                    title: {
                        display: true,
                        text: 'Project Comparison (Top ' + sortedProjects.length + ')'
                    },
                    legend: {
                        position: 'top'
                    },
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                const metric = metrics[ctx.datasetIndex];
                                const labels = [
                                    `Total: ${metric.totalTime.toFixed(1)}h`,
                                    `Sessions: ${metric.sessionCount}`,
                                    `Avg: ${metric.avgSessionLength.toFixed(1)}h`,
                                    `Subprojects: ${metric.subprojectCount}`,
                                    `Recency: ${metric.recency.toFixed(0)}/30`
                                ];
                                return `${metric.name}: ${labels[ctx.dataIndex]}`;
                            }
                        }
                    }
                },
                scales: {
                    r: {
                        beginAtZero: true,
                        max: 100,
                        ticks: {
                            stepSize: 20,
                            display: false
                        },
                        pointLabels: {
                            font: { size: 12 }
                        }
                    }
                }
            }
        });
    }

    // ========================================================================
    // Tag Bubble Chart
    // ========================================================================

    function tag_bubble_chart(data, ctx) {
        // Data format: [{ name, tag_id, total_time, project_count }]

        if (!data || data.length === 0) {
            utils.clearChart(ctx);
            return;
        }

        // Calculate bubble sizes (scale for visibility)
        const maxTime = Math.max(...data.map(t => t.total_time));
        const maxProjects = Math.max(...data.map(t => t.project_count));

        const bubbleData = data.map((tag, i) => ({
            x: tag.project_count,
            y: tag.total_time / 60, // hours
            r: Math.max(5, Math.sqrt(tag.total_time / 60) * 3), // Radius based on time
            name: tag.name,
            color: tag.color || utils.generateRandomColor(i, data.length)
        }));

        utils.clearChart(ctx);

        new Chart(ctx, {
            type: 'bubble',
            data: {
                datasets: [{
                    label: 'Tags',
                    data: bubbleData,
                    backgroundColor: bubbleData.map(b =>
                        b.color.startsWith('#')
                            ? b.color + '99' // Add alpha to hex
                            : b.color.replace(')', ', 0.6)').replace('hsl', 'hsla')
                    ),
                    borderColor: bubbleData.map(b => b.color),
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    title: {
                        display: true,
                        text: 'Tags by Project Count vs Time'
                    },
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                const point = ctx.raw;
                                return [
                                    `Tag: ${point.name}`,
                                    `Projects: ${point.x}`,
                                    `Total Time: ${point.y.toFixed(1)} hours`
                                ];
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        title: { display: true, text: 'Number of Projects' },
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1,
                            callback: function(value) {
                                if (Number.isInteger(value)) return value;
                            }
                        }
                    },
                    y: {
                        title: { display: true, text: 'Total Hours' },
                        beginAtZero: true
                    }
                }
            }
        });
    }

    // ========================================================================
    // Register charts
    // ========================================================================

    window.AutumnCharts.registerAll({
        histogram: session_histogram,
        radar: radar_chart,
        bubble: tag_bubble_chart
    });

})();
