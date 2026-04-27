import json
import io
import traceback
from contextlib import redirect_stdout
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = "dev-secret-key"

BASE_DIR = Path(__file__).resolve().parent
CHALLENGES_FILE = BASE_DIR / "challenges.json"
SUBMISSIONS_FILE = BASE_DIR / "submissions.json"


def load_json(path, default):
    if not path.exists():
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_challenges():
    return load_json(CHALLENGES_FILE, [])


def load_submissions():
    return load_json(SUBMISSIONS_FILE, [])


def save_submission(submission):
    submissions = load_submissions()
    submissions.append(submission)
    save_json(SUBMISSIONS_FILE, submissions)


def get_challenge(challenge_id):
    for challenge in load_challenges():
        if challenge["id"] == challenge_id:
            return challenge
    return None


def analyze_thinking(challenge, input_answer, output_answer, pseudocode):
    text = f"{input_answer} {output_answer} {pseudocode}".lower()
    keywords = challenge.get("thinking_keywords", [])
    found = [kw for kw in keywords if kw.lower() in text]
    missing = [kw for kw in keywords if kw.lower() not in text]

    feedback = []
    if input_answer.strip():
        feedback.append("Good: you identified the input.")
    else:
        feedback.append("Add a clearer description of the input.")

    if output_answer.strip():
        feedback.append("Good: you identified the output.")
    else:
        feedback.append("Add a clearer description of the output.")

    if pseudocode.strip():
        feedback.append("Good: you attempted step-by-step logic.")
    else:
        feedback.append("Write pseudocode before coding.")

    if missing:
        feedback.append("You may be missing these ideas in your explanation: " + ", ".join(missing))
    else:
        feedback.append("Nice job: your explanation includes the main problem-solving ideas.")

    score = 0
    if keywords:
        score = len(found) / len(keywords)

    return {
        "found": found,
        "missing": missing,
        "feedback": feedback,
        "score": round(score, 2)
    }


def run_student_code(challenge, code):
    function_name = challenge["function_name"]
    tests = challenge["tests"]

    result = {
        "status": "success",
        "stdout": "",
        "stderr": "",
        "tests": [],
        "all_passed": False
    }

    exec_globals = {"__builtins__": __builtins__}
    output_buffer = io.StringIO()

    try:
        with redirect_stdout(output_buffer):
            exec(code, exec_globals)

        if function_name not in exec_globals:
            result["status"] = "error"
            result["stderr"] = f"Function '{function_name}' was not defined."
            result["stdout"] = output_buffer.getvalue()
            return result

        func = exec_globals[function_name]

        for index, test in enumerate(tests, start=1):
            try:
                actual = func(*test["input"])
                passed = actual == test["expected"]
                result["tests"].append({
                    "name": test.get("name", f"test_{index}"),
                    "input": test["input"],
                    "expected": test["expected"],
                    "actual": actual,
                    "passed": passed
                })
            except Exception as test_error:
                result["tests"].append({
                    "name": test.get("name", f"test_{index}"),
                    "input": test["input"],
                    "expected": test["expected"],
                    "actual": f"Error: {str(test_error)}",
                    "passed": False
                })

        result["stdout"] = output_buffer.getvalue()
        result["all_passed"] = all(t["passed"] for t in result["tests"])

    except SyntaxError:
        result["status"] = "error"
        result["stderr"] = traceback.format_exc()
        result["stdout"] = output_buffer.getvalue()
    except Exception:
        result["status"] = "error"
        result["stderr"] = traceback.format_exc()
        result["stdout"] = output_buffer.getvalue()

    return result


@app.route("/")
def home():
    challenges = load_challenges()
    submissions = load_submissions()
    completed_ids = {s["challenge_id"] for s in submissions if s["all_passed"]}
    return render_template(
        "home.html",
        challenges=challenges,
        completed_ids=completed_ids
    )


@app.route("/challenge/<int:challenge_id>", methods=["GET", "POST"])
def challenge_page(challenge_id):
    challenge = get_challenge(challenge_id)
    if not challenge:
        flash("Challenge not found.")
        return redirect(url_for("home"))

    thinking_result = None
    code_result = None
    saved = False

    form_data = {
        "input_answer": "",
        "output_answer": "",
        "pseudocode": "",
        "code": challenge["starter_code"]
    }

    if request.method == "POST":
        form_data["input_answer"] = request.form.get("input_answer", "")
        form_data["output_answer"] = request.form.get("output_answer", "")
        form_data["pseudocode"] = request.form.get("pseudocode", "")
        form_data["code"] = request.form.get("code", "")

        thinking_result = analyze_thinking(
            challenge,
            form_data["input_answer"],
            form_data["output_answer"],
            form_data["pseudocode"]
        )

        code_result = run_student_code(challenge, form_data["code"])

        submission = {
            "challenge_id": challenge["id"],
            "challenge_title": challenge["title"],
            "input_answer": form_data["input_answer"],
            "output_answer": form_data["output_answer"],
            "pseudocode": form_data["pseudocode"],
            "code": form_data["code"],
            "thinking_score": thinking_result["score"],
            "thinking_feedback": thinking_result["feedback"],
            "test_results": code_result["tests"],
            "stdout": code_result["stdout"],
            "stderr": code_result["stderr"],
            "all_passed": code_result["all_passed"]
        }
        save_submission(submission)
        saved = True

    return render_template(
        "challenge.html",
        challenge=challenge,
        thinking_result=thinking_result,
        code_result=code_result,
        saved=saved,
        form_data=form_data
    )


@app.route("/progress")
def progress():
    challenges = load_challenges()
    submissions = load_submissions()

    latest_by_challenge = {}
    for submission in submissions:
        latest_by_challenge[submission["challenge_id"]] = submission

    completed_ids = []
    points = 0

    for challenge_id, submission in latest_by_challenge.items():
        if submission["thinking_score"] >= 0.75:
            points += 5

        if submission["all_passed"]:
            points += 10
            completed_ids.append(challenge_id)

    completed_ids.sort()

    return render_template(
        "progress.html",
        total_challenges=len(challenges),
        completed_count=len(completed_ids),
        points=points,
        completed_ids=completed_ids
    )


@app.route("/portfolio")
def portfolio():
    submissions = load_submissions()
    completed = [s for s in submissions if s["all_passed"]]

    latest_by_challenge = {}
    for submission in completed:
        latest_by_challenge[submission["challenge_id"]] = submission

    portfolio_items = list(latest_by_challenge.values())
    portfolio_items.sort(key=lambda x: x["challenge_id"])

    return render_template("portfolio.html", portfolio_items=portfolio_items)


if __name__ == "__main__":
    app.run(debug=True)