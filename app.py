import os
from datetime import date, datetime

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")

# --- Database -----------------------------------------------------------
# Vercel's filesystem is read-only except /tmp, and /tmp is wiped between
# invocations. So: use a hosted Postgres when DATABASE_URL is set (Neon,
# Supabase, Vercel Postgres...), otherwise fall back to a local SQLite file.
db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if db_url:
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
else:
    on_vercel = bool(os.environ.get("VERCEL"))
    db_url = "sqlite:////tmp/hotel.db" if on_vercel else "sqlite:///hotel.db"

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

CURRENCY = os.environ.get("CURRENCY", "$")
ACTIVE = ("confirmed", "checked_in")


# --- Models -------------------------------------------------------------
class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(10), unique=True, nullable=False)
    type = db.Column(db.String(30), nullable=False)
    price = db.Column(db.Integer, nullable=False)  # per night
    capacity = db.Column(db.Integer, default=2)
    status = db.Column(db.String(20), default="active")  # active | maintenance
    bookings = db.relationship("Booking", backref="room", lazy=True)


class Guest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(30))
    bookings = db.relationship("Booking", backref="guest", lazy=True)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    guest_id = db.Column(db.Integer, db.ForeignKey("guest.id"), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False)
    check_in = db.Column(db.Date, nullable=False)
    check_out = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default="confirmed")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def nights(self):
        return (self.check_out - self.check_in).days

    @property
    def total(self):
        return self.nights * self.room.price


# --- Helpers ------------------------------------------------------------
def room_state(room, today):
    if room.status == "maintenance":
        return "maintenance"
    if any(b.status == "checked_in" for b in room.bookings):
        return "occupied"
    if any(b.status == "confirmed" and b.check_in <= today < b.check_out
           for b in room.bookings):
        return "reserved"
    return "available"


def available_rooms(check_in, check_out):
    """Rooms that are in service and have no overlapping active booking."""
    busy = db.select(Booking.room_id).where(
        Booking.status.in_(ACTIVE),
        Booking.check_in < check_out,
        Booking.check_out > check_in,
    )
    return (Room.query.filter(Room.status == "active", ~Room.id.in_(busy))
            .order_by(Room.number).all())


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def seed():
    if Room.query.count():
        return
    plan = [("Standard", 80, 2, "10"), ("Deluxe", 120, 3, "20"), ("Suite", 220, 4, "30")]
    for rtype, price, cap, floor in plan:
        for n in range(1, 5):
            db.session.add(Room(number=f"{floor}{n}", type=rtype, price=price, capacity=cap))
    try:
        db.session.commit()
    except Exception:  # another serverless instance seeded first
        db.session.rollback()


@app.context_processor
def inject_globals():
    return {"currency": CURRENCY, "today": date.today()}


with app.app_context():
    db.create_all()
    seed()


# --- Routes -------------------------------------------------------------
@app.route("/")
def dashboard():
    today = date.today()
    rooms = Room.query.order_by(Room.number).all()
    states = {r.id: room_state(r, today) for r in rooms}
    in_service = [r for r in rooms if r.status == "active"]
    occupied = sum(1 for s in states.values() if s == "occupied")
    arrivals = Booking.query.filter_by(status="confirmed", check_in=today).all()
    departures = Booking.query.filter_by(status="checked_in", check_out=today).all()
    revenue = sum(b.total for b in Booking.query.filter(Booking.status.in_(("checked_in", "checked_out"))).all())
    stats = {
        "occupancy": round(100 * occupied / len(in_service)) if in_service else 0,
        "occupied": occupied,
        "free": sum(1 for s in states.values() if s == "available"),
        "arrivals": len(arrivals),
        "departures": len(departures),
        "revenue": revenue,
    }
    return render_template("dashboard.html", rooms=rooms, states=states, stats=stats,
                           arrivals=arrivals, departures=departures)


@app.route("/rooms", methods=["GET", "POST"])
def rooms():
    if request.method == "POST":
        number = request.form.get("number", "").strip()
        rtype = request.form.get("type", "Standard")
        try:
            price = int(request.form.get("price", 0))
            capacity = int(request.form.get("capacity", 2))
        except ValueError:
            price = capacity = 0
        if not number or price <= 0 or capacity <= 0:
            flash("Enter a room number, a nightly price and a capacity above zero.", "error")
        elif Room.query.filter_by(number=number).first():
            flash(f"Room {number} already exists.", "error")
        else:
            db.session.add(Room(number=number, type=rtype, price=price, capacity=capacity))
            db.session.commit()
            flash(f"Room {number} added.", "ok")
        return redirect(url_for("rooms"))
    all_rooms = Room.query.order_by(Room.number).all()
    states = {r.id: room_state(r, date.today()) for r in all_rooms}
    return render_template("rooms.html", rooms=all_rooms, states=states)


@app.post("/rooms/<int:room_id>/maintenance")
def toggle_maintenance(room_id):
    room = db.get_or_404(Room, room_id)
    if room.status == "active":
        if any(b.status in ACTIVE and b.check_out > date.today() for b in room.bookings):
            flash(f"Room {room.number} has upcoming bookings. Cancel or move them first.", "error")
            return redirect(url_for("rooms"))
        room.status = "maintenance"
        flash(f"Room {room.number} taken out of service.", "ok")
    else:
        room.status = "active"
        flash(f"Room {room.number} is back in service.", "ok")
    db.session.commit()
    return redirect(url_for("rooms"))


@app.route("/guests")
def guests():
    return render_template("guests.html", guests=Guest.query.order_by(Guest.name).all())


@app.route("/bookings")
def bookings():
    status = request.args.get("status", "all")
    q = Booking.query
    if status != "all":
        q = q.filter_by(status=status)
    return render_template("bookings.html", bookings=q.order_by(Booking.check_in.desc()).all(), status=status)


@app.route("/bookings/new", methods=["GET", "POST"])
def new_booking():
    data = request.form if request.method == "POST" else request.args
    check_in, check_out = parse_date(data.get("check_in")), parse_date(data.get("check_out"))
    dates_ok = bool(check_in and check_out and check_in < check_out and check_in >= date.today())

    if request.method == "POST":
        room = db.session.get(Room, int(data.get("room_id") or 0))
        name, email = data.get("name", "").strip(), data.get("email", "").strip().lower()
        if not (dates_ok and room and name and email):
            flash("Choose valid dates, a room, and enter the guest's name and email.", "error")
        elif room not in available_rooms(check_in, check_out):
            flash(f"Room {room.number} was just booked for those dates. Pick another.", "error")
        else:
            guest = Guest.query.filter_by(email=email).first()
            if not guest:
                guest = Guest(name=name, email=email, phone=data.get("phone", "").strip())
                db.session.add(guest)
                db.session.flush()
            db.session.add(Booking(guest_id=guest.id, room_id=room.id,
                                   check_in=check_in, check_out=check_out))
            db.session.commit()
            flash(f"Booked room {room.number} for {guest.name}.", "ok")
            return redirect(url_for("bookings"))

    free = available_rooms(check_in, check_out) if dates_ok else None
    if (data.get("check_in") or data.get("check_out")) and not dates_ok and request.method == "GET":
        flash("Check-out must be after check-in, and check-in can't be in the past.", "error")
    return render_template("new_booking.html", free=free, check_in=check_in, check_out=check_out)


@app.post("/bookings/<int:booking_id>/<action>")
def booking_action(booking_id, action):
    b = db.get_or_404(Booking, booking_id)
    transitions = {
        "check-in": ("confirmed", "checked_in", "Checked in"),
        "check-out": ("checked_in", "checked_out", "Checked out"),
        "cancel": ("confirmed", "cancelled", "Cancelled"),
    }
    if action not in transitions or b.status != transitions[action][0]:
        flash("That action isn't available for this booking.", "error")
    else:
        b.status = transitions[action][1]
        db.session.commit()
        flash(f"{transitions[action][2]}: {b.guest.name}, room {b.room.number}.", "ok")
    return redirect(request.referrer or url_for("bookings"))


if __name__ == "__main__":
    app.run(debug=True)
