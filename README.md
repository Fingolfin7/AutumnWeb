# Description

Web-based time and project tracking software based on [Autumn](https://github.com/Fingolfin7/Autumn). 
This application allows users to manage projects and subprojects, track time spent on various tasks, 
and visualize tracked data over a given period. It includes features such as session history viewing, 
word cloud generation from session notes, and dynamic charting for data visualization.

I developed a web based version of the original CLI version to allow users to track their time and projects from anywhere.

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
- **IDE:** The project is developed using PyCharm 2024.2.4.
- **Operating System:** The project is developed on Windows.

# Pages and Screenshots

## Projects Page
![Screenshot_11-11-2024_3356_fingolfin7 pythonanywhere com](https://github.com/user-attachments/assets/eadf27ca-96aa-4790-b922-994b6e0353e4)

### Manage Projects and Subprojects
![Screenshot_11-11-2024_33449_fingolfin7 pythonanywhere com](https://github.com/user-attachments/assets/14a5672e-7104-4ddb-9862-e74e013ad498)

### Timers Page
![Screenshot_11-11-2024_33621_fingolfin7 pythonanywhere com](https://github.com/user-attachments/assets/e5d371c4-f535-4492-be09-e796bdd00595)

## View Sessions History
![Screenshot_11-11-2024_33744_fingolfin7 pythonanywhere com](https://github.com/user-attachments/assets/26d6d230-a296-4196-8416-5975cd2e4e01)

## Visualize Tracked Data Over a give period
![charts](https://github.com/user-attachments/assets/23cc10d5-e5f1-421d-a1cb-8b45521d45fc)
