# Description

Web-based time and project tracking software based on [Autumn](https://github.com/Fingolfin7/Autumn). 
This application allows users to manage projects and subprojects, track time spent on various tasks, 
and visualize tracked data over a given period. It includes features such as session history viewing, 
word cloud generation from session notes, and dynamic charting for data visualization. And recently, a 
new Ïnsights" page where you can provide a subset of your session data to an LLM model and ask question about it!

I developed a web based version of the original CLI version to allow users to track their time and projects from anywhere. 
You can import the data from the CLI version and continue tracking projects and time on the web version. 
Data is stored in a SQLite database and can be exported to in JSON format for backup purposes or for importing into the CLI version.

I have deployed the application on PythonAnywhere. You can test it out [here](http://fingolfin7.pythonanywhere.com/).

# Setup

To set up the project locally, follow these steps:

1. **Clone the repository:**
    ```sh
    git clone https://github.com/Fingolfin7/AutumnWeb.git
    cd AutumnWeb
    ```

2. **Create and activate a virtual environment:**
    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. **Install the required dependencies:**
    ```sh
    pip install -r requirements.txt
    ```

4. **Apply migrations:**
    ```sh
    python manage.py migrate
    ```

5. **Run the development server:**
    ```sh
    python manage.py runserver
    ```

6. **Access the application:**
    Open your web browser and navigate to `http://127.0.0.1:8000/`.

7. **Adjust the default timezone:**
    The default timezone is set to `Europe/Prague`.
    To change these settings, update the `TIME_ZONE` in the  `settings.py` file.

8. **Create a superuser:**
    To access the admin panel, create a superuser by running.
    The admin panel can be accessed at `http://127/0.0.1:8000/admin`.

# Additional Information

- **JavaScript Libraries:** The project uses Chart.js for dynamic charting and wordcloud2.js for generating word clouds.

# Pages and Screenshots

## Projects Page
(Dark Mode)
![image](https://github.com/user-attachments/assets/dc04d27d-8665-4cab-af84-9c72ede1cd57)

(Light Mode)
![image](https://github.com/user-attachments/assets/d8e30b80-44f1-48ae-b5cf-5b5726e3ffe4)

## View Sessions History
![image](https://github.com/user-attachments/assets/ef04676e-363c-4c71-b305-99870eeb0f7a)


### Manage Projects and Subprojects

![image](https://github.com/user-attachments/assets/3aa4e01f-d66f-42d3-ad9a-0b7ff5495805)


### Timers Page
![image](https://github.com/user-attachments/assets/ed9a3e5f-ad4d-48d5-9a90-cd38548dea7f)

## Insights Page (AI page)

![image](https://github.com/user-attachments/assets/b9b7bc73-b61b-4a7c-abb7-c78dfb7c2818)


## Visualize Tracked Data Over a give period
![charts](https://github.com/user-attachments/assets/23cc10d5-e5f1-421d-a1cb-8b45521d45fc)
