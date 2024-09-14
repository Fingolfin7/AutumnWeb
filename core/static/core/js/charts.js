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
        }

        // get filter values (default to start of the current year and current date)
        let start_date = $('#start_date').val() || new Date(new Date().getFullYear(), 0, 1).toISOString().split('T')[0];
        let end_date = $('#end_date').val() || new Date().toISOString().split('T')[0];
        let project_name = $('#project-search').val() || "";

        console.log('project_name:', project_name, 'start_date:', start_date, 'end_date:', end_date);

        // change the date formats to date objects and convert the format to %m-%d-%Y
        start_date = start_date ? format_date(new Date(start_date)) : "";
        end_date = end_date ? format_date(new Date(end_date)) : "";

        get_project_data(type, start_date, end_date, project_name).then(data => {
            chart_types[type](data, canvas);
        }).catch(error => {
            console.error('Error fetching project data:', error);
        });
    }

    let selectType = $("#chart_type");
    let draw = $("#draw");

    render(selectType.val());

    draw.on('click', function(){
        let type = selectType.val();
        render(type);
    });

});

function get_project_data(type, start_date="", end_date="", project_name=""){
    // by default get the data from all the projects for all time
    let url = ""

    let requires_session_data = ['scatter', 'calendar', 'heatmap', 'scatter heatmap'];

    if (jQuery.inArray(type, requires_session_data) > -1){
        url = $('#sessions_link').val();
        if (project_name){
            url += `?project=${project_name}`;
        }
    }
    else{
        url = $("#projects_link").val();
    }

    if (start_date){
        if (!url.includes("?")){ // if the project filter is not present
            url += "?";
        }
        else{ // if the project filter is present just append the date filters
            url += "&";
        }

        url += `start=${start_date}`;
            if (end_date){
            url += `&end=${end_date}`;
        }
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

function generateRandomColor(element_position, element_count) {
    let hue = (element_position * 360) / element_count;
    return `hsl(${hue}, 100%, 70%)`;
}

function fillDates(minDate, maxDate) {
    // Generate all dates between minDate and maxDate
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

function format_date(date){
    let month = date.getMonth() + 1;
    let day = date.getDate();
    let year = date.getFullYear();

    //format date
    return `${month}-${day}-${year}`;
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
    // Extract session dates and durations
    const sessionData = data.map(item => {
        const startTime = new Date(item.start_time);
        const endTime = new Date(item.end_time);
        const duration = (endTime - startTime) / (1000 * 60 * 60); // duration in hours

        return {
            x: endTime,
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

    //sort the grouped data by project name
    groupedData.sort((a, b) => a[0].localeCompare(b[0]));

    // Generate colors based on project names
    const projectColors = {};

    groupedData.map((item, index) => {
        if (!projectColors[item[0]]) {
            projectColors[item[0]] = generateRandomColor(index, groupedData.length);
        }
    });

    console.log(projectColors);

    // Prepare the data for Chart.js
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

    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    // Calculate the difference in days between the first and last session
    let endDate = new Date(sessionData[0].x); // array is sorted in descending order
    let startDate  = new Date(sessionData[sessionData.length - 1].x);
    let chartUnit = getChartUnit(endDate, startDate);

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
        let date = new Date(item.start_time).toISOString().split('T')[0];
        let startTime = new Date(item.start_time);
        let endTime = new Date(item.end_time);
        let duration = (endTime - startTime) / (1000 * 60 * 60); // duration in hours

        if (!acc[date]) {
            acc[date] = duration;
        } else {
            acc[date] += duration;
        }
        return acc;
    }, {});

    //console.log("dateTotals: ", dateTotals);

    // let dates = Object.keys(dateTotals).map(date => new Date(date));
    // let minDate = new Date(Math.min(...dates));
    // let maxDate = new Date(Math.max(...dates));

    // sort dates and get the first date
    let year = new Date(Object.keys(dateTotals).sort()[0]).getFullYear();
    let minDate = new Date(year, 0, 1);
    let maxDate = new Date(year + 1, 0, 1);

    const dateList = fillDates(minDate, maxDate);

    // Create data array for each date with their duration
    const chartData = dateList.map(date => {
        let dateStr = date.toISOString().split('T')[0];
        return {
            x: date,
            y: date.getDay(), // 0 is Sunday, 6 is Saturday
            d: dateStr,
            v: dateTotals[dateStr] || 0
        };
    });

    // Find maximum duration for scaling color intensity
    const maxDuration = Math.max(...chartData.map(d => d.v));

    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    // Calculate the difference in days between the first and last session
    let startDate = new Date(chartData[0].x); // array is sorted in descending order
    let endDate  = new Date(chartData[chartData.length - 1].x);
    let chartUnit = getChartUnit(endDate, startDate);

    // Create the chart
    const scales = {
        x: {
            type: 'time',
            position: 'bottom',
            offset: true,
            time: {
                unit: chartUnit,
                round: 'week',
                // displayFormats: {
                //     month: 'MMM dd'
                // }
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
            grid: {
                display: false,
                drawBorder: false,
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
                    if (alpha === 0) {
                        return `rgba(82, 76, 66, 0.37)`;
                    }
                    return `rgba(0, 128, 0, ${alpha})`;
                },
                borderWidth: 1,
                hoverBackgroundColor: 'yellow',
                hoverBorderColor: 'yellowgreen',
                // width(c) {
                //     let a = c.chart.chartArea || {};
                //     return (a.right - a.left) / Math.round(dateList.length/5.5);
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
                    displayColors: true,
                    callbacks: {
                        title() {
                           return ''
                        },
                        label(context) {
                            const data = context.dataset.data[context.dataIndex];
                            return [
                                new Date(data.d).toLocaleDateString('en-US', {
                                    weekday: 'short', // Short day (e.g., Thu)
                                    day: 'numeric',   // Day (e.g., 1, 2, 3)
                                    month: 'short',   // Short month (e.g., Apr)
                                    year: 'numeric'   // Year (e.g., 2023)
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


