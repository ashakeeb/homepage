from flask import Flask, render_template, request
from database import create_table, register_user, check_login

app = Flask(__name__)

create_table()


@app.route("/")
def home():
    return """
    <h1>Welcome to my website!</h1>
    <a href="/register">Register</a><br>
    <a href="/login">Login</a>
    """


@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        if register_user(username, password):
            return "Registration successful! <a href='/login'>Login</a>"
        else:
            return "Username already exists."

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        if check_login(username, password):
            return "Login successful!"
        else:
            return "Wrong username or password."

    return render_template("login.html")


if __name__ == "__main__":
    app.run(debug=True)
