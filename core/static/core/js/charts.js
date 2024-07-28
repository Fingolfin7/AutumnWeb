$(document).ready(function(){
    function render(type) {
        // get the chart canvas, and selected type from the "chart_type" select element
        let canvas = $("#chart")[0].getContext('2d');

        // make a map of the chart type to the function that will render the chart
        let chart_types = {
            'pie': pie_chart,
            'bar': bar_graph,
            'scatter': scatter_graph,
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

    let requires_session_data = ['scatter', 'calendar', 'heatmap'];

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

