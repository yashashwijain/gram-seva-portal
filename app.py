from flask import Flask, request, render_template_string, redirect
import pymysql, boto3, uuid

DB_HOST = "gramseva-db.c96gqqgsqzqk.us-east-1.rds.amazonaws.com"
DB_USER = "admin"
DB_PASS = "PUT_YOUR_PASSWORD_HERE"
DB_NAME = "gramseva"
BUCKET = "gramseva-documents-2206"
TOPIC = "arn:aws:sns:us-east-1:014740689725:gramseva-notifications"

app = Flask(__name__)
s3 = boto3.client("s3", region_name="us-east-1")
sns = boto3.client("sns", region_name="us-east-1")

def db():
    return pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS,
                           database=DB_NAME, cursorclass=pymysql.cursors.DictCursor)

PAGE = """
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gram Seva Portal</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head><body class="bg-light">
<nav class="navbar navbar-dark bg-success mb-4"><div class="container">
<span class="navbar-brand">Gram Seva Portal</span>
<div><a class="text-white me-3" href="/">Apply</a>
<a class="text-white me-3" href="/status">Track Status</a>
<a class="text-white" href="/officer">Officer</a></div></div></nav>
<div class="container" style="max-width:800px">{{ body|safe }}</div>
<p class="text-center text-muted mt-4 small">Served by: {{ host }}</p>
</body></html>
"""

def page(body):
    import socket
    return render_template_string(PAGE, body=body, host=socket.gethostname())

@app.route("/health")
def health():
    return "OK"

@app.route("/")
def home():
    return page("""
<h3>Apply for a Service</h3>
<form method="post" action="/submit" enctype="multipart/form-data" class="card card-body">
<input class="form-control mb-2" name="name" placeholder="Full name" required>
<input class="form-control mb-2" name="village" placeholder="Village" required>
<input class="form-control mb-2" name="phone" placeholder="Phone" required>
<input class="form-control mb-2" type="email" name="email" placeholder="Email" required>
<select class="form-select mb-2" name="service">
<option>Income Certificate</option><option>Residence Certificate</option>
<option>Caste Certificate</option><option>Old Age Pension</option>
<option>Farmer Subsidy</option><option>Grievance</option></select>
<label class="small text-muted">Upload document (PDF/JPG/PNG)</label>
<input class="form-control mb-3" type="file" name="doc" required>
<button class="btn btn-success">Submit Application</button></form>""")

@app.route("/submit", methods=["POST"])
def submit():
    f = request.files["doc"]
    key = "uploads/" + uuid.uuid4().hex[:8] + "_" + f.filename.replace(" ", "_")
    s3.upload_fileobj(f, BUCKET, key, ExtraArgs={"ServerSideEncryption": "AES256"})
    con = db()
    with con.cursor() as c:
        c.execute("INSERT INTO applications (name,village,phone,email,service,document_key) VALUES (%s,%s,%s,%s,%s,%s)",
                  (request.form["name"], request.form["village"], request.form["phone"],
                   request.form["email"], request.form["service"], key))
        con.commit()
        app_id = c.lastrowid
    con.close()
    sns.publish(TopicArn=TOPIC, Subject="Gram Seva: Application Received",
                Message=f"Application ID {app_id} for {request.form['service']} by {request.form['name']} received. Status: Pending.")
    return page(f'<div class="alert alert-success"><h4>Application submitted!</h4>Your Application ID is <b>{app_id}</b>. Save it to track status.</div><a href="/">Back</a>')

@app.route("/status", methods=["GET", "POST"])
def status():
    result = ""
    if request.method == "POST":
        con = db()
        with con.cursor() as c:
            c.execute("SELECT * FROM applications WHERE id=%s", (request.form["id"],))
            r = c.fetchone()
        con.close()
        result = (f'<div class="alert alert-info">ID {r["id"]}: {r["service"]} for {r["name"]} - <b>{r["status"]}</b></div>'
                  if r else '<div class="alert alert-danger">Not found</div>')
    return page('<h3>Track Status</h3><form method="post" class="d-flex mb-3"><input class="form-control me-2" name="id" placeholder="Application ID" required><button class="btn btn-success">Check</button></form>' + result)

@app.route("/officer")
def officer():
    con = db()
    with con.cursor() as c:
        c.execute("SELECT * FROM applications ORDER BY id DESC")
        rows = c.fetchall()
    con.close()
    html = '<h3>Officer Dashboard</h3><table class="table table-sm bg-white"><tr><th>ID</th><th>Name</th><th>Village</th><th>Service</th><th>Status</th><th>Action</th></tr>'
    for r in rows:
        html += (f'<tr><td>{r["id"]}</td><td>{r["name"]}</td><td>{r["village"]}</td><td>{r["service"]}</td><td>{r["status"]}</td>'
                 f'<td><a class="btn btn-sm btn-success" href="/update/{r["id"]}/Approved">Approve</a> '
                 f'<a class="btn btn-sm btn-danger" href="/update/{r["id"]}/Rejected">Reject</a></td></tr>')
    return page(html + "</table>")

@app.route("/update/<int:id>/<status>")
def update(id, status):
    if status not in ("Approved", "Rejected"):
        return "Invalid", 400
    con = db()
    with con.cursor() as c:
        c.execute("UPDATE applications SET status=%s WHERE id=%s", (status, id))
        con.commit()
    con.close()
    sns.publish(TopicArn=TOPIC, Subject="Gram Seva: Status Update",
                Message=f"Application ID {id} has been {status}.")
    return redirect("/officer")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
