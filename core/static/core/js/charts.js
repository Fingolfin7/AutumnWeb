$(document).ready(function(){
    function render(type) {
        // get the chart canvas, and selected type from the "chart_type" select element
        let canvas = $("#chart");


        get_project_data().then(data => {
            pie_chart(data, canvas);
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

function get_project_data() {
    // by default get the data from all the projects for all time
    let url = $("#base_url").val();
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


function pie_chart(data, canvas) {
    // Clear the canvas

    // Prepare the data for Google Charts
    let chartData = [['Category', 'Total Time']]; // Initial header row
    let project_totals = data.map(({name, total_time}) => [name, total_time/60]); // Convert seconds to minutes
    chartData = chartData.concat(project_totals);

    // Load the Google Charts API
    google.charts.load('current', {'packages':['corechart']});

    // Set callback to run when API is loaded
    google.charts.setOnLoadCallback(drawChart);

    console.log(chartData);

    // Function to draw the chart
    function drawChart() {
        console.log('drawing chart');
        var dataTable = google.visualization.arrayToDataTable(chartData);

        // Options for the pie chart
        var options = {
            title: 'Project Time Distribution',
            //pieHole: 0.4, // create a donut chart
            width: '100%', // Set width to 100% for responsive scaling
            // height: 500    // Set a fixed height
        };

        // Draw the pie chart
        var chart = new google.visualization.PieChart(canvas[0]);
        chart.draw(dataTable, options);
    }
}
