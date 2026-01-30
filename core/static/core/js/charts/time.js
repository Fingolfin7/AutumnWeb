/**
 * Time-based Charts Module
 * Calendar and Heatmap charts (matrix-based visualizations)
 */

(function() {
    const utils = window.AutumnCharts.utils;

    // ========================================================================
    // Calendar Chart (GitHub-style activity calendar)
    // ========================================================================

    function calendar_graph(data, ctx, title = "Projects Calendar") {
        // Aggregate data by date
        const dateTotals = data.reduce((acc, item) => {
            let date = new Date(item.start_time).toISOString().split('T')[0];
            let startTime = new Date(item.start_time);
            let endTime = new Date(item.end_time);
            let duration = (endTime - startTime) / (1000 * 60 * 60);

            if (!acc[date]) {
                acc[date] = duration;
            } else {
                acc[date] += duration;
            }
            return acc;
        }, {});

        // Sort dates and get the first date's year
        let year = new Date(Object.keys(dateTotals).sort()[0]).getFullYear();
        let minDate = new Date(year, 0, 1);
        let maxDate = new Date(year + 1, 0, 1);

        const dateList = utils.fillDates(minDate, maxDate);

        // Create data array for each date
        const chartData = dateList.map(date => {
            let dateStr = date.toISOString().split('T')[0];
            return {
                x: date,
                y: date.getDay(),
                d: dateStr,
                v: dateTotals[dateStr] || 0
            };
        });

        const maxDuration = Math.max(...chartData.map(d => d.v));

        utils.clearChart(ctx);

        let startDate = new Date(chartData[0].x);
        let endDate = new Date(chartData[chartData.length - 1].x);
        let chartUnit = utils.getChartUnit(endDate, startDate);

        const scales = {
            x: {
                type: 'time',
                position: 'bottom',
                offset: true,
                time: {
                    unit: chartUnit,
                    round: 'week',
                },
                ticks: { maxRotation: 0 },
                grid: { display: false, drawBorder: false }
            },
            y: {
                type: 'linear',
                min: 0,
                max: 6,
                reverse: true,
                position: 'left',
                ticks: {
                    maxRotation: 0,
                    callback: function(value) {
                        return ['Sat', 'Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri'][(value)];
                    }
                },
                grid: { display: false, drawBorder: false }
            }
        };

        new Chart(ctx, {
            type: 'matrix',
            data: {
                datasets: [{
                    data: chartData,
                    backgroundColor(c) {
                        let value = c.dataset.data[c.dataIndex].v;
                        let alpha = value / maxDuration;
                        if (alpha === 0) {
                            return `rgba(82, 76, 66, 0.37)`;
                        }
                        return `rgba(0, 128, 0, ${alpha})`;
                    },
                    borderWidth: 1,
                    hoverBackgroundColor: 'yellow',
                    hoverBorderColor: 'yellowgreen',
                }]
            },
            options: {
                aspectRatio: 5,
                responsive: true,
                maintainAspectRatio: true,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        displayColors: true,
                        callbacks: {
                            title() { return ''; },
                            label(context) {
                                const data = context.dataset.data[context.dataIndex];
                                return [
                                    new Date(data.d).toLocaleDateString('en-US', {
                                        weekday: 'short',
                                        day: 'numeric',
                                        month: 'short',
                                        year: 'numeric'
                                    }),
                                    data.v.toFixed(2) + ' hours'
                                ];
                            }
                        }
                    },
                },
                scales: scales,
            }
        });
    }

    // ========================================================================
    // Heatmap Chart (Weekday x Hour matrix)
    // ========================================================================

    function heatmap_graph(data, ctx) {
        // Prepare storage: 7 days * 24 hours
        const totals = Array.from({ length: 7 }, () => Array(24).fill(0));
        const counts = Array.from({ length: 7 }, () => Array(24).fill(0));

        // Bin each session into hour-blocks
        data.forEach(item => {
            const t0 = new Date(item.start_time);
            const t1 = new Date(item.end_time);
            let cur = new Date(t0);

            while (cur < t1) {
                const nextHour = new Date(cur);
                nextHour.setHours(cur.getHours() + 1, 0, 0, 0);
                const blockEnd = nextHour < t1 ? nextHour : t1;
                const durHrs = (blockEnd - cur) / 36e5;

                const wd = cur.getDay();
                const hr = cur.getHours();

                totals[wd][hr] += durHrs;
                counts[wd][hr] += 1;

                cur = blockEnd;
            }
        });

        // Build matrix data and find max average
        let maxAvg = 0;
        const matrixData = [];
        for (let wd = 0; wd < 7; wd++) {
            for (let hr = 0; hr < 24; hr++) {
                const cnt = counts[wd][hr];
                const avg = cnt > 0 ? totals[wd][hr] / cnt : 0;
                if (avg > maxAvg) maxAvg = avg;
                matrixData.push({ x: wd, y: hr, v: avg });
            }
        }

        utils.clearChart(ctx);

        new Chart(ctx, {
            type: 'matrix',
            data: {
                datasets: [{
                    label: 'Avg session length (hrs)',
                    data: matrixData,
                    width(ctx) {
                        const c = ctx.chart;
                        const area = c.chartArea;
                        const full = area ? (area.right - area.left) : c.width;
                        return full / 7 - 1;
                    },
                    height(ctx) {
                        const c = ctx.chart;
                        const area = c.chartArea;
                        const full = area ? (area.bottom - area.top) : c.height;
                        return full / 24 - 1;
                    },
                    backgroundColor(ctx) {
                        const v = ctx.dataset.data[ctx.dataIndex].v;
                        const alpha = maxAvg ? v / maxAvg : 0;
                        return `rgba(0, 128, 0, ${alpha})`;
                    },
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    title: {
                        display: true,
                        text: 'Weekly Hourly Heatmap'
                    },
                    tooltip: {
                        callbacks: {
                            title() { return ''; },
                            label(ctx) {
                                const { x: wd, y: hr, v } = ctx.dataset.data[ctx.dataIndex];
                                const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
                                return `${days[wd]} ${hr}:00 → ${(v || 0).toFixed(2)} h avg`;
                            }
                        }
                    },
                    legend: { display: false }
                },
                scales: {
                    x: {
                        type: 'linear',
                        min: 0,
                        max: 6,
                        ticks: {
                            stepSize: 1,
                            callback(v) { return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][v]; }
                        },
                        title: { display: true, text: 'Weekday' },
                        grid: { display: false }
                    },
                    y: {
                        type: 'linear',
                        min: 0,
                        max: 23,
                        reverse: true,
                        ticks: {
                            stepSize: 1,
                            callback(v) { return `${v}:00`; }
                        },
                        title: { display: true, text: 'Time of Day' },
                        grid: { display: false }
                    }
                }
            }
        });
    }

    // ========================================================================
    // Register charts
    // ========================================================================

    window.AutumnCharts.registerAll({
        calendar: calendar_graph,
        heatmap: heatmap_graph
    });

})();
