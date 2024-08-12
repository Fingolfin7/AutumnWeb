$(document).ready(function(){
    function render(type) {
        // get the chart canvas, and selected type from the "chart_type" select element
        let canvas = $("#chart")[0].getContext('2d');

        // make a map of the chart type to the function that will render the chart
        let chart_types = {
            'pie': pie_chart,
            'bar': bar_graph,
            'scatter': scatter_graph,
            'calendar': calendar_graph,
            'scatter heatmap': scatter_heatmap,
        }

        get_project_data(type).then(data => {
            chart_types[type](data, canvas);
        }).catch(error => {
            console.error('Error fetching project data:', error);
        });
    }

    let selectType = $("#chart_type");

    render(selectType.val());

    selectType.on('change', function(){
        let type = $(this).val();
        render(type);
    });

});

function get_project_data(type) {
    // by default get the data from all the projects for all time
    let url = ""

    let requires_session_data = ['scatter', 'calendar', 'heatmap', 'scatter heatmap'];

    if (jQuery.inArray(type, requires_session_data) > -1){
        url = $('#sessions_link').val();
    }
    else{
        url = $("#projects_link").val();
    }

    console.log(url);

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

// Function to generate a random color
function generateRandomColor(element_position, element_count) {
    let hue = (element_position * 360) / element_count;
    return `hsl(${hue}, 100%, 50%)`;
}

function pie_chart(data, ctx) {
    // Generate colors dynamically based on the number of data points
    const colors = data.map((element, index) => generateRandomColor(index, data.length));

    // Prepare the data for Chart.js
    const chartData = {
        labels: data.map(item => item.name),
        datasets: [{
            data: data.map(item => item.total_time/60),
            backgroundColor: colors,
            borderWidth: 0.5
        }]
    };

    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    // Create the chart
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


function bar_graph(data, ctx) {
    // Generate colors dynamically based on the number of data points
    let colors = data.map((element, index) => generateRandomColor(index, data.length));

    // Prepare the data for Chart.js
    const chartData = {
        labels: data.map(item => item.name),
        datasets: [{
            label: 'Project Totals',
            data: data.map(item => item.total_time / 60),
            backgroundColor: colors,
            borderWidth: 0.5
        }]
    };

    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    // Create the chart
    new Chart(ctx, {
        type: 'bar',
        data: chartData,
        options: {
            responsive: true,
            indexAxis: 'y',
        }
    });
}


function scatter_graph(data, ctx) {
    console.log(data[0]);

    // Extract session dates and durations
    const sessionData = data.map(item => {
        const startTime = new Date(item.start_time);
        const endTime = new Date(item.end_time);
        const duration = (endTime - startTime) / (1000 * 60 * 60); // duration in hours

        return {
            x: startTime,
            y: duration,
            projectName: item.project.name
        };
    });


    // Group data by project
    const groupedData = Object.entries(
        sessionData.reduce((acc, item) => {
            if (!acc[item.projectName]) acc[item.projectName] = [];
            acc[item.projectName].push(item);
            return acc;
        }, {})
    );

    // Generate colors based on project names
    const projectColors = {};
    data.forEach((item, index) => {
        if (!projectColors[item.project.name]) {
            projectColors[item.project.name] = generateRandomColor(index, sessionData.length);
        }
    });

    // Prepare the data for Chart.js
    const chartData = {
        datasets: groupedData.map(([projectName, data]) => ({
            label: projectName,
            data: data,
            backgroundColor: projectColors[projectName],
        }))
    };

    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    let chartUnit = 'week';
    if (sessionData.length < 7){
        chartUnit = 'day';
    }
    else if (sessionData.length < 30){
        chartUnit = 'week';
    }
    else if (sessionData.length < 365){
        chartUnit = 'month';
    }
    else{
        chartUnit = 'year';
    }

    // Create the chart
    new Chart(ctx, {
        type: 'scatter',
        data: chartData,
        options: {
            responsive: true,
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: chartUnit
                    },
                    title: {
                        display: true,
                        text: 'Date'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Duration (hours)'
                    },
                    beginAtZero: true
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
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


function calendar_graph(data, ctx, title = "Projects Calendar") {
    // Aggregate data by date
    const dateTotals = data.reduce((acc, item) => {
        const date = new Date(item.start_time).toISOString().split('T')[0];
        const startTime = new Date(item.start_time);
        const endTime = new Date(item.end_time);
        const duration = (endTime - startTime) / (1000 * 60 * 60); // duration in hours

        if (!acc[date]) {
            acc[date] = duration;
        } else {
            acc[date] += duration;
        }
        return acc;
    }, {});

    // Get all dates for the current year
    const year = new Date().getFullYear();
    const start = new Date(year, 0, 1);
    const end = new Date(year + 1, 0, 1);
    const dateList = [];
    for (let date = start; date < end; date.setDate(date.getDate() + 1)) {
        dateList.push(new Date(date));
    }

    // Create data array for each date with their duration
    const chartData = dateList.map(date => {
        const dateStr = date.toISOString().split('T')[0];
        return {
            x: date,
            y: date.getDay(),
            d: dateStr,
            v: dateTotals[dateStr] || 0
        };
    });

    // Find maximum duration for scaling color intensity
    const maxDuration = Math.max(...chartData.map(d => d.v));
    console.log("max Duration: " + maxDuration);

    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    // Create the chart
    const scales = {
        x: {
            type: 'time',
            position: 'bottom',
            offset: true,
            time: {
                unit: 'week',
                round: 'week',
                displayFormats: {
                    month: 'MMM dd'
                }
            },
            ticks: {
                maxRotation: 0
            },
            grid: {
                display: false,
                drawBorder: false
            }
        },
        y: {
            type: 'time',
            offset: true,
            time: {
                unit: 'day',
                displayFormats: {
                    day: 'ddd'
                }
            },
            reverse: true,
            position: 'left',
            ticks: {
                maxRotation: 0,
                callback: function(value) {
                    return moment(value, 'e').format('ddd');
                }
            },
            grid: {
                display: false,
                drawBorder: false
            }
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
                    if (alpha < 0.1){
                        return `rgb(137, 148, 153)`;
                    }
                    return `rgba(0, 128, 0, ${alpha})`;
                },
                borderWidth: 1,
                hoverBackgroundColor: 'yellow',
                hoverBorderColor: 'yellowgreen',
                width(c) {
                    let a = c.chart.chartArea || {};
                    return (a.right - a.left) / 53;
                }
                // height(c) {
                //     const a = c.chart.chartArea || {};
                //     return (a.bottom - a.top) / 7;
                // }
            }]
        },
        options: {
            aspectRatio: 5,
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    displayColors: false,
                    callbacks: {
                        title() {
                            return '';
                        },
                        label(context) {
                            const v = context.dataset.data[context.dataIndex];
                            return ['date: ' + v.d, 'total: ' + v.v.toFixed(2)];
                        }
                    }
                },
            },
            scales: scales,
            // layout: {
            //     padding: {
            //         top: 10
            //     }
            // }
        }
    });
}




function scatter_heatmap(data, ctx) {
    // Group data by date and sum durations
    const groupedData = data.reduce((acc, item) => {
        const startTime = new Date(item.start_time);
        const endTime = new Date(item.end_time);
        const duration = (endTime - startTime) / (1000 * 60 * 60); // duration in hours
        const date = startTime.toISOString().split('T')[0]; // YYYY-MM-DD format

        if (!acc[date]) {
            acc[date] = { total: 0, projects: {} };
        }
        acc[date].total += duration;

        if (!acc[date].projects[item.project.name]) {
            acc[date].projects[item.project.name] = 0;
        }
        acc[date].projects[item.project.name] += duration;

        return acc;
    }, {});

    // Convert grouped data to array format required by Chart.js
    const heatmapData = Object.entries(groupedData).map(([date, value]) => {
        const [year, month, day] = date.split('-').map(Number);
        return {
            x: new Date(year, month - 1, day), // JavaScript months are 0-indexed
            y: new Date(year, month - 1, day).getDay(), // 0 (Sunday) to 6 (Saturday)
            value: value.total,
            projects: value.projects
        };
    });

    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    // Create the chart
    new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [{
                label: 'Time Spent',
                data: heatmapData,
                backgroundColor: (context) => {
                    const value = context.raw.value;
                    const alpha = Math.min(value / 8, 1); // Assuming 8 hours is max intensity
                    return `rgba(75, 192, 192, ${alpha})`;
                },
                pointRadius: 10,
                pointHoverRadius: 12,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'month',
                        displayFormats: {
                            month: 'MMM YYYY'
                        }
                    },
                    title: {
                        display: true,
                        text: 'Date'
                    }
                },
                y: {
                    type: 'linear',
                    min: 0,
                    max: 6,
                    reverse: true,
                    ticks: {
                        stepSize: 1,
                        callback: function(value, index, values) {
                            return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][value];
                        }
                    },
                    title: {
                        display: true,
                        text: 'Day of Week'
                    }
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        title: function(context) {
                            return context[0].raw.x.toDateString();
                        },
                        label: function(context) {
                            const value = context.raw;
                            let label = `Total: ${value.value.toFixed(2)} hours\n`;
                            Object.entries(value.projects).forEach(([project, hours]) => {
                                label += `${project}: ${hours.toFixed(2)} hours\n`;
                            });
                            return label.split('\n');
                        }
                    }
                },
                legend: {
                    display: false
                }
            }
        }
    });
}

