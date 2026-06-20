#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate English Class lesson content as local JSON files.
Target: 200 lessons per level (1200+ total).

Run: python scripts/generate_english_class_content.py
"""
import json
import os
import random
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "english-class")
LESSONS_PER_LEVEL = 200
MIN_LINES = 12
MAX_LINES = 20
QUIZ_COUNT = 5
VOCAB_COUNT = 5

LEVELS = {
    "a1": {
        "name": "A1 Beginner",
        "description": "Basic greetings, everyday words, and simple conversations.",
        "categories": {
            "greetings": "Greetings",
            "family": "Family",
            "food": "Food",
            "numbers": "Numbers",
            "colors": "Colors",
            "school": "School",
            "daily_life": "Daily Life",
        },
    },
    "a2": {
        "name": "A2 Elementary",
        "description": "Practical situations: shopping, travel, and services.",
        "categories": {
            "shopping": "Shopping",
            "travel": "Travel",
            "restaurant": "Restaurant",
            "hotel": "Hotel",
            "hospital": "Hospital",
            "transportation": "Transportation",
        },
    },
    "b1": {
        "name": "B1 Intermediate",
        "description": "Work, social life, and handling everyday problems.",
        "categories": {
            "work": "Work",
            "office": "Office",
            "phone_calls": "Phone Calls",
            "banking": "Banking",
            "friendships": "Friendships",
            "housing": "Housing",
        },
    },
    "b2": {
        "name": "B2 Upper Intermediate",
        "description": "Professional settings, meetings, and complex discussions.",
        "categories": {
            "business": "Business",
            "meetings": "Meetings",
            "presentations": "Presentations",
            "negotiation": "Negotiation",
            "leadership": "Leadership",
        },
    },
    "c1": {
        "name": "C1 Advanced",
        "description": "Academic, technical, and nuanced professional English.",
        "categories": {
            "academic": "Academic Discussions",
            "technology": "Technology",
            "politics": "Politics",
            "research": "Research",
            "management": "Management",
        },
    },
    "c2": {
        "name": "C2 Mastery",
        "description": "Sophisticated debates, philosophy, and expert communication.",
        "categories": {
            "debates": "Advanced Debates",
            "philosophy": "Philosophy",
            "international_relations": "International Relations",
            "professional_communication": "Professional Communication",
        },
    },
}

# Shared context pools for unique combinations
PLACES = [
    "the library", "the park", "the café", "school", "the market", "the bus stop",
    "the community center", "the bookstore", "the gym", "the clinic", "downtown",
    "the train station", "the museum", "the supermarket", "the post office",
    "the pharmacy", "the bank", "the office", "the airport", "the hotel lobby",
    "the restaurant", "the hospital waiting room", "the apartment building",
    "the sports center", "the language school", "the coworking space",
]
NAMES = [
    "Sarah", "James", "Emma", "David", "Maria", "Tom", "Lisa", "Paul", "Anna",
    "Chris", "Nina", "Omar", "Grace", "Kevin", "Sofia", "Brian", "Yuki", "Alex",
    "Helen", "Mark", "Priya", "Daniel", "Laura", "Sam", "Rachel",
]
TIMES = [
    "this morning", "this afternoon", "this evening", "on Monday", "on Friday",
    "at nine o'clock", "at noon", "after work", "before class", "on the weekend",
    "tomorrow", "next week", "later today", "early", "at six thirty",
]
FOODS = [
    "sandwich", "salad", "pasta", "rice and chicken", "soup", "fruit", "bread",
    "eggs and toast", "pizza", "fish", "vegetables", "tea and biscuits",
    "coffee and cake", "noodles", "a burger", "yogurt", "smoothie",
]
ITEMS = [
    "a notebook", "a map", "an umbrella", "a ticket", "a phone charger",
    "a gift", "medicine", "a textbook", "a receipt", "a reservation",
    "a boarding pass", "a shopping list", "a water bottle", "a laptop",
    "an appointment card", "a house key", "a bus card", "a form",
]
MOODS = ["fine", "good", "well", "a bit tired", "busy", "relaxed", "excited", "happy"]
ACTIVITIES = [
    "study for an exam", "meet a friend", "go shopping", "visit family",
    "finish a project", "take a walk", "prepare dinner", "catch the bus",
    "return a book", "ask for directions", "make a reservation",
    "open a bank account", "schedule a meeting", "give a presentation",
    "review a contract", "discuss a policy", "analyze data",
]
WEATHER = ["sunny", "rainy", "cloudy", "windy", "cold", "warm", "hot"]
COLORS = ["red", "blue", "green", "yellow", "black", "white", "orange", "purple", "brown", "pink"]
NUMBERS_CTX = ["three", "five", "ten", "twelve", "fifteen", "twenty", "thirty", "forty", "fifty", "one hundred"]

STOP_WORDS = {
    "that", "this", "with", "have", "from", "they", "been", "were", "said",
    "each", "which", "their", "will", "would", "there", "about", "what",
    "when", "make", "like", "time", "very", "just", "know", "take", "into",
    "your", "some", "them", "then", "well", "also", "only", "come", "over",
    "such", "give", "most", "tell", "does", "good", "much", "sure", "thank",
    "thanks", "hello", "please", "really", "right", "think", "going", "today",
    "tomorrow", "sorry", "great", "nice", "need", "want", "been", "being",
}

# Category vocabulary glossaries (word, definition)
CATEGORY_VOCAB = {
    "greetings": [
        ("hello", "A word used when you meet someone."),
        ("goodbye", "A word used when you leave."),
        ("welcome", "A friendly word when someone arrives."),
        ("introduction", "Telling someone your name or who you are."),
        ("greeting", "Words you say when you meet a person."),
        ("polite", "Showing good manners."),
        ("neighbor", "A person who lives near you."),
        ("visitor", "A person who comes to a place."),
        ("handshake", "Shaking hands when you meet."),
        ("pleasant", "Nice and enjoyable."),
    ],
    "family": [
        ("parent", "A mother or father."),
        ("sibling", "A brother or sister."),
        ("cousin", "A child of your aunt or uncle."),
        ("relative", "A person in your family."),
        ("household", "All the people living in one home."),
        ("grandparent", "A mother or father of your parent."),
        ("nephew", "The son of your brother or sister."),
        ("reunion", "A meeting of family members together."),
        ("generation", "People born around the same time."),
        ("upbringing", "The way a child is raised."),
    ],
    "food": [
        ("ingredient", "Something used to make food."),
        ("recipe", "Instructions for cooking a dish."),
        ("appetite", "The desire to eat."),
        ("portion", "The amount of food for one person."),
        ("delicious", "Having a very good taste."),
        ("grocery", "Food bought at a store."),
        ("beverage", "A drink."),
        ("vegetarian", "A person who does not eat meat."),
        ("spicy", "Having a hot, strong flavor."),
        ("fresh", "Recently made or picked."),
    ],
    "numbers": [
        ("quantity", "An amount of something."),
        ("calculate", "To find an answer using numbers."),
        ("total", "The complete amount."),
        ("dozen", "A group of twelve."),
        ("percentage", "A part of one hundred."),
        ("estimate", "A rough guess of an amount."),
        ("double", "Two times the same amount."),
        ("fraction", "A part of a whole number."),
        ("average", "A typical amount in the middle."),
        ("digit", "A single number from 0 to 9."),
    ],
    "colors": [
        ("shade", "A particular type of a color."),
        ("bright", "Strong and easy to see."),
        ("pale", "Light and not strong."),
        ("pattern", "A repeated design."),
        ("fabric", "Cloth material."),
        ("decorate", "To make something look nicer."),
        ("contrast", "A clear difference between things."),
        ("vivid", "Very bright and clear."),
        ("neutral", "Not strong in color."),
        ("dye", "A substance that changes color."),
    ],
    "school": [
        ("homework", "Work students do at home."),
        ("assignment", "A task given by a teacher."),
        ("semester", "Half of a school year."),
        ("lecture", "A talk given to students."),
        ("deadline", "The last day to finish work."),
        ("campus", "The land and buildings of a school."),
        ("tuition", "Money paid for education."),
        ("scholarship", "Money given to help study."),
        ("curriculum", "The subjects taught at a school."),
        ("graduate", "To finish school successfully."),
    ],
    "daily_life": [
        ("routine", "Things you do regularly."),
        ("errand", "A short trip to do a task."),
        ("commute", "Travel between home and work."),
        ("laundry", "Washing clothes."),
        ("appointment", "A planned meeting time."),
        ("schedule", "A plan of times for activities."),
        ("household", "Related to the home."),
        ("chore", "A small job at home."),
        ("neighbor", "Someone living nearby."),
        ("relax", "To rest and feel calm."),
    ],
    "shopping": [
        ("receipt", "Paper showing what you paid."),
        ("discount", "A lower price."),
        ("checkout", "The place where you pay."),
        ("aisle", "A passage between shelves."),
        ("bargain", "Something bought at a good price."),
        ("refund", "Money returned for a return."),
        ("cashier", "A person who takes payment."),
        ("merchandise", "Goods for sale."),
        ("coupon", "A ticket for a lower price."),
        ("purchase", "Something you buy."),
    ],
    "travel": [
        ("luggage", "Bags you take on a trip."),
        ("passport", "An official travel document."),
        ("itinerary", "A plan for a trip."),
        ("destination", "The place you travel to."),
        ("boarding", "Getting on a plane or ship."),
        ("customs", "Official checks at a border."),
        ("souvenir", "Something bought to remember a trip."),
        ("delay", "When something happens later."),
        ("departure", "Leaving a place."),
        ("sightseeing", "Visiting interesting places."),
    ],
    "restaurant": [
        ("menu", "A list of food and drinks."),
        ("reservation", "Booking a table in advance."),
        ("appetizer", "A small dish before the main meal."),
        ("dessert", "Sweet food after a meal."),
        ("waiter", "A person who serves food."),
        ("bill", "The check for your meal."),
        ("tip", "Extra money for good service."),
        ("cuisine", "A style of cooking."),
        ("allergy", "A bad reaction to certain food."),
        ("special", "A dish recommended today."),
    ],
    "hotel": [
        ("check-in", "Arriving and registering at a hotel."),
        ("check-out", "Leaving and paying at a hotel."),
        ("suite", "A large hotel room."),
        ("concierge", "A hotel helper for guests."),
        ("amenity", "A useful hotel feature."),
        ("housekeeping", "Staff who clean rooms."),
        ("lobby", "The entrance area of a hotel."),
        ("booking", "A reserved room."),
        ("vacancy", "An available room."),
        ("complimentary", "Free of charge."),
    ],
    "hospital": [
        ("symptom", "A sign that you are ill."),
        ("prescription", "A doctor's order for medicine."),
        ("appointment", "A planned visit to a doctor."),
        ("emergency", "A sudden serious problem."),
        ("diagnosis", "A doctor's identification of an illness."),
        ("treatment", "Care to make someone better."),
        ("pharmacy", "A place that sells medicine."),
        ("insurance", "Coverage for medical costs."),
        ("recovery", "Getting better after illness."),
        ("ward", "A section of a hospital."),
    ],
    "transportation": [
        ("platform", "Where you wait for a train."),
        ("fare", "The price of a ticket."),
        ("transfer", "Changing from one vehicle to another."),
        ("schedule", "Times when transport runs."),
        ("commuter", "A person who travels regularly."),
        ("detour", "A different route."),
        ("terminal", "A main station or stop."),
        ("route", "The path a vehicle follows."),
        ("passenger", "A person traveling in a vehicle."),
        ("departure", "The time a vehicle leaves."),
    ],
    "work": [
        ("colleague", "A person you work with."),
        ("deadline", "The last day to finish work."),
        ("overtime", "Extra hours beyond normal work."),
        ("promotion", "A move to a higher job."),
        ("interview", "A meeting to get a job."),
        ("resume", "A document about your work history."),
        ("salary", "Money paid for work."),
        ("workload", "The amount of work to do."),
        ("supervisor", "A person who manages workers."),
        ("benefits", "Extra advantages from a job."),
    ],
    "office": [
        ("meeting", "A planned discussion at work."),
        ("printer", "A machine that puts text on paper."),
        ("deadline", "The final date for a task."),
        ("conference", "A formal meeting."),
        ("agenda", "A list of topics for a meeting."),
        ("workspace", "The area where you work."),
        ("supplies", "Materials needed for work."),
        ("memo", "A short written message at work."),
        ("conference", "A group discussion."),
        ("workflow", "The steps of a work process."),
    ],
    "phone_calls": [
        ("voicemail", "A recorded phone message."),
        ("dial", "To enter a phone number."),
        ("hold", "To wait on the phone."),
        ("callback", "Returning a phone call."),
        ("extension", "An internal phone number."),
        ("signal", "Phone connection quality."),
        ("receiver", "The part you hold to your ear."),
        ("conference", "A call with several people."),
        ("unavailable", "Not able to answer."),
        ("confirm", "To make sure something is correct."),
    ],
    "banking": [
        ("account", "A record of money at a bank."),
        ("deposit", "Putting money into an account."),
        ("withdrawal", "Taking money out."),
        ("balance", "The amount of money left."),
        ("interest", "Extra money the bank pays."),
        ("loan", "Money borrowed from a bank."),
        ("transfer", "Moving money between accounts."),
        ("statement", "A record of account activity."),
        ("pin", "A secret number for a card."),
        ("overdraft", "Spending more than you have."),
    ],
    "friendships": [
        ("trust", "Belief that someone is honest."),
        ("loyalty", "Strong support for a friend."),
        ("confide", "To share private feelings."),
        ("reconnect", "To contact again after time apart."),
        ("supportive", "Giving help and encouragement."),
        ("apologize", "To say sorry."),
        ("forgive", "To stop being angry."),
        ("companionship", "Spending time together."),
        ("bond", "A close connection."),
        ("reliable", "Someone you can depend on."),
    ],
    "housing": [
        ("lease", "A contract to rent a home."),
        ("landlord", "The owner of a rented home."),
        ("tenant", "A person who rents a home."),
        ("utilities", "Services like water and electricity."),
        ("mortgage", "A loan to buy a home."),
        ("renovation", "Work to improve a home."),
        ("inspection", "Checking the condition of a home."),
        ("deposit", "Money paid to secure a rental."),
        ("furnished", "A home with furniture included."),
        ("neighborhood", "The area around a home."),
    ],
    "business": [
        ("revenue", "Money a company earns."),
        ("profit", "Money left after costs."),
        ("stakeholder", "A person with interest in a company."),
        ("strategy", "A long-term plan."),
        ("market", "Buyers and sellers of products."),
        ("competitor", "Another business in the same field."),
        ("investment", "Money put in to grow a business."),
        ("partnership", "A business relationship."),
        ("expansion", "Growing a business."),
        ("quarterly", "Happening every three months."),
    ],
    "meetings": [
        ("agenda", "Topics planned for a meeting."),
        ("minutes", "A written record of a meeting."),
        ("facilitate", "To help a meeting run well."),
        ("consensus", "General agreement."),
        ("action", "A task decided in a meeting."),
        ("attendee", "A person at a meeting."),
        ("postpone", "To move to a later time."),
        ("brief", "A short summary."),
        ("follow-up", "A later check on a topic."),
        ("quorum", "Enough people to hold a meeting."),
    ],
    "presentations": [
        ("slide", "One screen in a presentation."),
        ("audience", "People listening to a talk."),
        ("visual", "A picture or chart shown."),
        ("outline", "The main points of a talk."),
        ("delivery", "The way you give a speech."),
        ("engage", "To keep the audience interested."),
        ("conclude", "To finish a presentation."),
        ("handout", "Paper given to the audience."),
        ("feedback", "Comments after a talk."),
        ("rehearse", "To practice before presenting."),
    ],
    "negotiation": [
        ("offer", "Something proposed in a deal."),
        ("counteroffer", "A reply to an offer."),
        ("compromise", "Each side gives something."),
        ("deadlock", "When talks stop progressing."),
        ("leverage", "Power in a negotiation."),
        ("concession", "Something given to reach agreement."),
        ("terms", "The conditions of a deal."),
        ("mutual", "Shared by both sides."),
        ("deadline", "A time limit for agreement."),
        ("finalize", "To complete a deal."),
    ],
    "leadership": [
        ("delegate", "To give tasks to others."),
        ("vision", "A clear idea of the future."),
        ("mentor", "An experienced guide."),
        ("accountability", "Responsibility for results."),
        ("initiative", "Taking action without being asked."),
        ("empower", "To give people authority."),
        ("culture", "Shared values in a group."),
        ("feedback", "Information about performance."),
        ("coaching", "Helping someone improve."),
        ("integrity", "Being honest and fair."),
    ],
    "academic": [
        ("thesis", "A long paper for a degree."),
        ("hypothesis", "An idea tested by research."),
        ("citation", "A reference to a source."),
        ("peer", "Another researcher in the field."),
        ("seminar", "A small academic class."),
        ("discipline", "An area of study."),
        ("methodology", "The way research is done."),
        ("literature", "Published academic work."),
        ("abstract", "A short summary of a paper."),
        ("plagiarism", "Using others' work without credit."),
    ],
    "technology": [
        ("software", "Programs that run on computers."),
        ("hardware", "Physical computer equipment."),
        ("algorithm", "A set of computer steps."),
        ("database", "Organized stored information."),
        ("cybersecurity", "Protection from digital attacks."),
        ("innovation", "A new technical idea."),
        ("automation", "Machines doing tasks."),
        ("interface", "How a user interacts with tech."),
        ("bandwidth", "Data transfer capacity."),
        ("prototype", "An early version of a product."),
    ],
    "politics": [
        ("policy", "A plan of government action."),
        ("legislation", "A proposed or passed law."),
        ("constituent", "A person represented by a leader."),
        ("coalition", "Groups working together."),
        ("referendum", "A public vote on an issue."),
        ("bipartisan", "Supported by two major parties."),
        ("regulation", "An official rule."),
        ("campaign", "Efforts to win an election."),
        ("diplomacy", "Managing relations between states."),
        ("mandate", "Authority from voters."),
    ],
    "research": [
        ("variable", "Something measured in a study."),
        ("sample", "A group studied."),
        ("data", "Collected information."),
        ("analysis", "Examination of information."),
        ("finding", "A result discovered."),
        ("replicate", "To repeat a study."),
        ("bias", "A unfair influence on results."),
        ("validity", "How correct a measure is."),
        ("ethics", "Moral rules for research."),
        ("publication", "Sharing research formally."),
    ],
    "management": [
        ("objective", "A goal to achieve."),
        ("KPI", "A key measure of success."),
        ("resource", "Something used to reach goals."),
        ("prioritize", "To decide what is most important."),
        ("oversight", "Supervision of work."),
        ("benchmark", "A standard for comparison."),
        ("stakeholder", "Someone affected by decisions."),
        ("efficiency", "Doing tasks with little waste."),
        ("scalable", "Able to grow in size."),
        ("governance", "Rules for running an organization."),
    ],
    "debates": [
        ("argument", "A reason supporting a view."),
        ("rebuttal", "A response to an opposing point."),
        ("rhetoric", "Persuasive use of language."),
        ("premise", "An idea that supports a conclusion."),
        ("fallacy", "A mistake in reasoning."),
        ("proposition", "A statement to debate."),
        ("moderator", "A person who guides a debate."),
        ("cross-examination", "Challenging the other side."),
        ("consensus", "Agreement after discussion."),
        ("dialectic", "Discussion of opposing ideas."),
    ],
    "philosophy": [
        ("ethics", "The study of right and wrong."),
        ("metaphysics", "The nature of reality."),
        ("epistemology", "The study of knowledge."),
        ("existential", "Related to human existence."),
        ("paradox", "An idea that seems contradictory."),
        ("utilitarian", "Focused on greatest good."),
        ("virtue", "A moral quality."),
        ("determinism", "The idea that events are fixed."),
        ("free will", "The power to choose."),
        ("phenomenology", "Study of lived experience."),
    ],
    "international_relations": [
        ("treaty", "An agreement between countries."),
        ("sovereignty", "A nation's independent authority."),
        ("sanction", "A penalty on a country."),
        ("alliance", "A partnership between nations."),
        ("embassy", "A country's office abroad."),
        ("humanitarian", "Help for people in crisis."),
        ("multilateral", "Involving many countries."),
        ("bilateral", "Between two countries."),
        ("geopolitics", "Politics influenced by geography."),
        ("summit", "A meeting of world leaders."),
    ],
    "professional_communication": [
        ("concise", "Short and clear."),
        ("tone", "The feeling of a message."),
        ("clarity", "Being easy to understand."),
        ("diplomatic", "Careful and polite in difficult situations."),
        ("articulate", "Expressing ideas clearly."),
        ("nuance", "A small difference in meaning."),
        ("correspondence", "Written communication."),
        ("protocol", "Official rules of behavior."),
        ("stakeholder", "Someone with an interest."),
        ("deliverable", "A promised work result."),
    ],
}

# Title templates per category
TITLE_TEMPLATES = {
    "greetings": [
        "Meeting at {place}", "{time} Greeting", "Welcoming {name}",
        "Saying Hi at {place}", "First Day Greeting", "Neighbors at {place}",
        "Morning Chat with {name}", "Evening Hello", "Quick Greeting at School",
        "Friendly Welcome", "Introduction at {place}", "Casual Hello {time}",
        "Greeting a Visitor", "Polite Hello", "Campus Greeting",
        "Community Hello", "Meeting {name} Again", "Short Greeting",
        "Warm Welcome", "Saying Hi Before Class",
    ],
    "family": [
        "Family Dinner Talk", "Visiting Grandparents", "Sibling Chat",
        "Planning a Reunion", "Helping at Home", "Birthday at Home",
        "Family Rules Talk", "Cousins Visiting", "Parents and Homework",
        "Weekend with Family", "Cooking with Mom", "Family Photo Day",
        "House Chores", "Family Outing", "Brother and Sister",
        "Family Breakfast", "Calling Relatives", "Pet in the Family",
        "Family Schedule", "Sunday with Family",
    ],
    "food": [
        "At the Grocery Store", "Cooking {food}", "Lunch at School",
        "Trying New Food", "Breakfast at Home", "Dinner Plans",
        "Recipe Sharing", "Hungry After Sports", "Food Allergies Talk",
        "Favorite Meal", "Buying {food}", "Kitchen Help",
        "Holiday Feast", "Snack Time", "Restaurant Choice",
        "Healthy Eating", "Meal Preparation", "Food Shopping List",
        "Sharing Dessert", "Cooking Together",
    ],
    "numbers": [
        "Counting at the Market", "Telling Time", "Phone Numbers",
        "Age and Birthday", "Prices at the Store", "Room Numbers",
        "Sports Scores", "Bus Route Numbers", "Calendar Dates",
        "Measuring Ingredients", "Classroom Numbers", "Bank Balance",
        "Ticket Numbers", "Temperature Reading", "Distance and Time",
        "Budget Planning", "Score Keeping", "Appointment Times",
        "Counting Money", "Math in Daily Life",
    ],
    "colors": [
        "Choosing Paint Colors", "Clothes at the Store", "Art Class Colors",
        "Describing a Sunset", "Room Decoration", "Favorite Colors",
        "Traffic Light Colors", "Garden Flowers", "Shopping for Fabric",
        "Painting a Picture", "Color Matching", "Birthday Balloons",
        "Sports Team Colors", "Weather Sky Colors", "Gift Wrapping",
        "Color Blindness Talk", "Interior Design", "School Project Colors",
        "Nature Walk Colors", "Colorful Market",
    ],
    "school": [
        "First Day of Class", "Asking the Teacher", "Group Project",
        "Library Research", "School Lunch", "Sports Tryouts",
        "Exam Preparation", "Bus to School", "Parent Meeting",
        "Graduation Plans", "Class Presentation", "Study Group",
        "School Supplies", "Club Meeting", "Field Trip",
        "Homework Help", "Computer Lab", "School Event",
        "Timetable Change", "After-School Activity",
    ],
    "daily_life": [
        "Morning Routine", "Doing Laundry", "Weather Talk",
        "Cleaning the House", "Evening Walk", "Setting an Alarm",
        "Recycling Day", "Neighborhood News", "Relaxing at Home",
        "Planning the Week", "Grocery Errand", "Fixing Something at Home",
        "Daily Exercise", "Making Tea", "Organizing a Room",
        "Phone Battery Low", "Weekend Plans", "Commute Talk",
        "Healthy Habits", "Quiet Evening",
    ],
    "shopping": [
        "Buying {item}", "At the Checkout", "Looking for a Discount",
        "Returning an Item", "Shopping with {name}", "Comparing Prices",
        "Grocery Aisle Help", "Trying on Clothes", "Online Order Pickup",
        "Shopping List", "Payment Problem", "Seasonal Sale",
        "Gift Shopping", "Supermarket Trip", "Electronics Store",
        "Fitting Room", "Coupon Savings", "Market Bargain",
        "Shopping Budget", "Customer Service",
    ],
    "travel": [
        "At the Airport", "Train to {place}", "Hotel Directions",
        "Travel Itinerary", "Lost Luggage", "Border Questions",
        "Sightseeing Plan", "Booking a Tour", "Travel Insurance",
        "Delayed Flight", "Souvenir Shopping", "Map Reading",
        "Hostel Check-in", "Road Trip Plans", "Travel Companion",
        "Passport Control", "Weekend Getaway", "Bus to {place}",
        "Travel Budget", "Arrival at {place}",
    ],
    "restaurant": [
        "Ordering {food}", "Table Reservation", "Asking About the Menu",
        "Food Allergy", "Splitting the Bill", "Special of the Day",
        "Slow Service", "Takeaway Order", "Birthday Dinner",
        "Lunch Meeting", "Spicy Dish", "Dessert Choice",
        "Restaurant Recommendation", "Large Group Booking", "Tip Discussion",
        "Vegetarian Options", "Wine with Dinner", "Quick Lunch",
        "Complaint Polite", "Celebration Meal",
    ],
    "hotel": [
        "Hotel Check-in", "Room Problem", "Asking for Towels",
        "Late Check-out", "Hotel Breakfast", "Booking Extension",
        "Concierge Help", "Wi-Fi Password", "Noise Complaint",
        "Room Upgrade", "Lost Key Card", "Hotel Gym",
        "Wake-up Call", "Laundry Service", "Business Center",
        "Taxi from Hotel", "Housekeeping Request", "Mini Bar Question",
        "Conference Room", "Checkout Bill",
    ],
    "hospital": [
        "Doctor Appointment", "Describing Symptoms", "Pharmacy Visit",
        "Emergency Room", "Insurance Question", "Follow-up Visit",
        "Prescription Refill", "Blood Test", "Waiting Room",
        "Nurse Instructions", "Dental Checkup", "Vaccination",
        "Recovery Advice", "Medical History", "Referral to Specialist",
        "Hospital Directions", "Pain Level", "Appointment Reschedule",
        "Health Insurance", "Feeling Better",
    ],
    "transportation": [
        "Bus to {place}", "Train Platform", "Missed Connection",
        "Taxi Ride", "Metro Card", "Traffic Delay",
        "Bike Rental", "Ferry Schedule", "Car Pool",
        "Parking Problem", "Road Directions", "Ticket Machine",
        "Rush Hour", "Airport Shuttle", "Schedule Change",
        "Seat Reservation", "Transport App", "Flat Tire",
        "Commute Time", "Last Train",
    ],
    "work": [
        "Job Interview", "First Day at Work", "Deadline Pressure",
        "Team Project", "Salary Discussion", "Work from Home",
        "Performance Review", "Office Conflict", "New Colleague",
        "Training Session", "Promotion News", "Sick Day Call",
        "Career Goals", "Overtime Request", "Client Meeting",
        "Work-Life Balance", "Job Offer", "Office Equipment",
        "Break Room Chat", "Project Update",
    ],
    "office": [
        "Morning Stand-up", "Printer Jam", "Meeting Room Booking",
        "Office Supplies", "Email Problem", "Desk Move",
        "Conference Call", "Office Party", "Fire Drill",
        "Shared Workspace", "IT Support", "Office Temperature",
        "Visitor Badge", "Internal Memo", "Coffee Machine",
        "File Organization", "Office Hours", "Team Lunch",
        "Presentation Setup", "End of Quarter",
    ],
    "phone_calls": [
        "Scheduling by Phone", "Wrong Number", "Leaving Voicemail",
        "Customer Support Call", "Confirming Appointment", "Bad Signal",
        "Conference Call", "Returning a Call", "Phone Interview",
        "Delivery Call", "Bank Phone Service", "Reminder Call",
        "Urgent Message", "Hold Please", "Extension Number",
        "Callback Request", "Survey Call", "Family Phone Chat",
        "Doctor's Office Call", "Late for Meeting Call",
    ],
    "banking": [
        "Opening an Account", "ATM Problem", "Transfer Money",
        "Loan Inquiry", "Credit Card Issue", "Bank Statement",
        "Currency Exchange", "Savings Goal", "Direct Deposit",
        "Lost Card", "Mortgage Question", "Investment Option",
        "Overdraft Fee", "Mobile Banking", "Joint Account",
        "Wire Transfer", "Interest Rate", "Branch Visit",
        "Budget Planning", "PIN Change",
    ],
    "friendships": [
        "Catching Up with {name}", "Apologizing to a Friend", "Making Plans",
        "Supporting a Friend", "Old Friend Visit", "Trust Talk",
        "Group Hangout", "Misunderstanding", "Celebrating Success",
        "Long Distance Friendship", "Borrowing Something", "Honest Advice",
        "Weekend with Friends", "Forgiving a Mistake", "Shared Hobby",
        "Friend Moving Away", "Coffee with {name}", "Birthday Surprise",
        "Study Buddy", "Reconnecting Online",
    ],
    "housing": [
        "Apartment Viewing", "Lease Signing", "Utility Setup",
        "Noisy Neighbor", "Rent Payment", "Home Repair",
        "Moving Day", "Furnished Apartment", "Roommate Rules",
        "Landlord Message", "Home Inspection", "Mortgage Talk",
        "Garden Space", "Parking Spot", "Internet Installation",
        "Broken Heating", "Security Deposit", "House Hunting",
        "Cleaning Before Moving", "Neighborhood Safety",
    ],
    "business": [
        "Quarterly Results", "Market Analysis", "New Partnership",
        "Investor Meeting", "Product Launch", "Competitor News",
        "Business Strategy", "Cost Reduction", "Sales Target",
        "Customer Feedback", "Expansion Plan", "Risk Assessment",
        "Brand Image", "Supply Chain", "Revenue Growth",
        "Board Update", "Startup Pitch", "Franchise Talk",
        "Business Ethics", "Trade Agreement",
    ],
    "meetings": [
        "Weekly Team Meeting", "Agenda Review", "Action Items",
        "Postponed Meeting", "Brainstorm Session", "Budget Meeting",
        "Project Kickoff", "Status Update", "Conflict in Meeting",
        "Remote Meeting", "Meeting Minutes", "Time Management",
        "Stakeholder Meeting", "Decision Making", "Follow-up Tasks",
        "All-Hands Meeting", "Client Presentation", "Meeting Overrun",
        "Facilitator Role", "Closing Summary",
    ],
    "presentations": [
        "Opening a Presentation", "Handling Questions", "Technical Demo",
        "Slide Design", "Nervous Speaker", "Audience Engagement",
        "Closing Remarks", "Time Limit", "Visual Aids",
        "Team Presentation", "Sales Pitch", "Research Talk",
        "Feedback Session", "Rehearsal", "Project Defense",
        "Conference Talk", "Data Charts", "Storytelling",
        "Equipment Failure", "Q and A",
    ],
    "negotiation": [
        "Salary Negotiation", "Contract Terms", "Price Discussion",
        "Deadline Extension", "Partnership Deal", "Counteroffer",
        "Win-Win Solution", "Tough Negotiation", "Final Offer",
        "Compromise Reach", "Vendor Contract", "Lease Terms",
        "Trade-off Talk", "Negotiation Stalemate", "Closing a Deal",
        "Terms and Conditions", "Mutual Benefits", "Bargaining",
        "Renewal Negotiation", "Agreement Signed",
    ],
    "leadership": [
        "Team Motivation", "Delegating Tasks", "Vision Meeting",
        "Difficult Feedback", "Crisis Leadership", "Mentoring Talk",
        "Culture Building", "Leadership Style", "Accountability",
        "Change Management", "Succession Planning", "Trust Building",
        "Remote Team Lead", "Conflict Resolution", "Strategic Goals",
        "Coaching Session", "Ethical Decision", "Empowering Staff",
        "Performance Goals", "Leadership Workshop",
    ],
    "academic": [
        "Seminar Discussion", "Thesis Advisor", "Research Proposal",
        "Peer Review", "Literature Review", "Class Debate",
        "Citation Help", "Study Method", "Academic Integrity",
        "Conference Paper", "Lab Results", "Theory vs Practice",
        "Graduate Program", "Scholarship Application", "Office Hours",
        "Group Research", "Abstract Writing", "Field Study",
        "Academic Publishing", "Exam Strategy",
    ],
    "technology": [
        "Software Update", "Cybersecurity Briefing", "AI Discussion",
        "Cloud Migration", "Bug Report", "Product Roadmap",
        "Tech Support", "Data Privacy", "Startup Technology",
        "Automation Impact", "Digital Transformation", "API Integration",
        "Hardware Upgrade", "Tech Ethics", "User Experience",
        "System Outage", "Innovation Lab", "Open Source",
        "Machine Learning", "Tech Interview",
    ],
    "politics": [
        "Policy Debate", "Election Discussion", "Legislation Review",
        "Public Opinion", "Campaign Strategy", "Voting Rights",
        "International Policy", "Local Government", "Media Interview",
        "Coalition Building", "Regulation Impact", "Civic Duty",
        "Debate Preparation", "Constituent Concern", "Budget Vote",
        "Diplomatic Talk", "Referendum", "Party Platform",
        "Ethics in Politics", "Town Hall",
    ],
    "research": [
        "Study Design", "Data Collection", "Research Ethics",
        "Survey Results", "Hypothesis Test", "Peer Collaboration",
        "Funding Application", "Field Notes", "Statistical Analysis",
        "Replication Study", "Research Gap", "Methodology Choice",
        "Interview Data", "Publication Plan", "Conference Submission",
        "Bias Discussion", "Sample Size", "Research Timeline",
        "Literature Gap", "Findings Presentation",
    ],
    "management": [
        "KPI Review", "Resource Allocation", "Priority Setting",
        "Team Performance", "Process Improvement", "Risk Management",
        "Stakeholder Update", "Budget Approval", "Hiring Decision",
        "Operational Efficiency", "Change Initiative", "Quality Control",
        "Strategic Planning", "Crisis Management", "Vendor Selection",
        "Goal Alignment", "Management Training", "Succession Plan",
        "Governance Review", "Quarterly Objectives",
    ],
    "debates": [
        "Opening Argument", "Rebuttal Round", "Ethical Debate",
        "Policy Argument", "Cross-Examination", "Closing Statement",
        "Moderator Question", "Evidence Challenge", "Parliamentary Style",
        "Value Debate", "Proposition Defense", "Opposition Case",
        "Timed Rebuttal", "Audience Question", "Moral Dilemma",
        "Historical Debate", "Scientific Controversy", "Free Speech",
        "Climate Argument", "Technology Ethics",
    ],
    "philosophy": [
        "Ethics Discussion", "Free Will Debate", "Knowledge and Truth",
        "Existential Question", "Moral Philosophy", "Mind and Body",
        "Political Philosophy", "Aesthetics Talk", "Logic Puzzle",
        "Virtue Ethics", "Utilitarian View", "Philosophy of Science",
        ("Ancient vs Modern",),  # fix - typo
    ],
    "international_relations": [
        "Treaty Negotiation", "Embassy Meeting", "Trade Summit",
        "Humanitarian Aid", "Security Council", "Alliance Talk",
        "Sanctions Debate", "Cultural Exchange", "Border Dispute",
        "Peace Talks", "UN Resolution", "Bilateral Meeting",
        "Refugee Policy", "Global Economy", "Climate Agreement",
        "Diplomatic Protocol", "Foreign Policy", "Regional Cooperation",
        "International Law", "Summit Preparation",
    ],
    "professional_communication": [
        "Executive Email", "Difficult Conversation", "Client Update",
        "Negotiation Tone", "Formal Report", "Meeting Follow-up",
        "Crisis Communication", "Presentation Feedback", "Networking Talk",
        "Apology Letter", "Persuasive Message", "Cross-Cultural Email",
        "Concise Writing", "Stakeholder Letter", "Policy Memo",
        "Media Statement", "Team Announcement", "Professional Apology",
        "Board Correspondence", "Clarity in Writing",
    ],
}

# Fix philosophy typo in TITLE_TEMPLATES
TITLE_TEMPLATES["philosophy"] = [
    "Ethics Discussion", "Free Will Debate", "Knowledge and Truth",
    "Existential Question", "Moral Philosophy", "Mind and Body",
    "Political Philosophy", "Aesthetics Talk", "Logic Puzzle",
    "Virtue Ethics", "Utilitarian View", "Philosophy of Science",
    "Ancient vs Modern", "Metaphysics Talk", "Epistemology Class",
    "Paradox Discussion", "Moral Dilemma", "Justice Debate",
    "Consciousness Talk", "Philosophy Seminar",
]

# Dialogue beat templates: (speaker, template) pairs chained together
def _level_opener(level, ctx):
    if level in ("a1", "a2"):
        return [
            ("A", "Hello. How are you?"),
            ("B", f"I'm {ctx['mood']}, thank you. How are you?"),
            ("A", "I'm doing well."),
        ]
    if level in ("b1", "b2"):
        return [
            ("A", f"Hi {ctx['name']}. Do you have a moment?"),
            ("B", "Sure. What's on your mind?"),
            ("A", f"I wanted to talk about {ctx['topic']}."),
        ]
    return [
        ("A", f"I'd like to discuss {ctx['topic']} with you."),
        ("B", "Certainly. I'm prepared to explore that."),
        ("A", "There are a few points worth examining."),
    ]


def _level_closer(level, ctx):
    if level in ("a1", "a2"):
        return [
            ("A", "Thank you for talking with me."),
            ("B", "You're welcome. See you soon."),
        ]
    if level in ("b1", "b2"):
        return [
            ("A", "That clears things up. I appreciate your help."),
            ("B", "Glad I could assist. Let's follow up {time}."),
        ]
    return [
        ("A", "I think we've addressed the key issues adequately."),
        ("B", "Agreed. We should revisit this after further reflection."),
    ]


def _beat_pool():
    """Shared conversation beats — filled with context at runtime."""
    beats = [
        ("A", "Have you been to {place} recently?"),
        ("B", "Yes, I went there {time}."),
        ("A", "Did you need {item}?"),
        ("B", "Actually, I was looking for something else."),
        ("A", "Maybe we can go together next time."),
        ("B", "That sounds like a good idea."),
        ("A", "By the way, how is {name}?"),
        ("B", "{name} is doing well and staying busy."),
        ("A", "I heard the weather will be {weather} tomorrow."),
        ("B", "Then I should take an umbrella."),
        ("A", "What are you doing {time}?"),
        ("B", "I'm planning to {activity}."),
        ("A", "I need to finish something important first."),
        ("B", "I understand. Take your time."),
        ("A", "Could you help me with a small favor?"),
        ("B", "Of course. Tell me what you need."),
        ("A", "I forgot to bring {item} today."),
        ("B", "You can borrow mine if you want."),
        ("A", "The bus was late again this morning."),
        ("B", "Traffic has been terrible lately."),
        ("A", "I bought some {food} for lunch."),
        ("B", "That sounds delicious."),
        ("A", "Are you free {time}?"),
        ("B", "Let me check my schedule."),
        ("A", "I called you yesterday but missed you."),
        ("B", "Sorry, I was in a meeting."),
        ("A", "This place is busier than usual."),
        ("B", "Maybe there is a sale today."),
        ("A", "I have an appointment at the clinic."),
        ("B", "I hope everything goes well."),
        ("A", "We should leave a little earlier."),
        ("B", "Good point. I will be ready."),
        ("A", "Did you hear the news about the new shop?"),
        ("B", "Yes, everyone is talking about it."),
        ("A", "I prefer the blue one over the red one."),
        ("B", "The blue color looks brighter."),
        ("A", "How much does it cost altogether?"),
        ("B", "About twenty dollars with tax."),
        ("A", "My phone battery is very low."),
        ("B", "There is a charger on the desk."),
        ("A", "I studied until late last night."),
        ("B", "No wonder you look tired today."),
        ("A", "The teacher gave us extra homework."),
        ("B", "We should start early this week."),
        ("A", "I met your cousin at the market."),
        ("B", "Small world. What did you talk about?"),
        ("A", "The train arrives in ten minutes."),
        ("B", "Then we need to hurry to the platform."),
        ("A", "Would you like tea or coffee?"),
        ("B", "Tea, please. With a little milk."),
        ("A", "I saved a seat for you."),
        ("B", "That was very kind of you."),
        ("A", "The document is on your desk."),
        ("B", "Thanks. I will review it this afternoon."),
        ("A", "Our client asked for an update."),
        ("B", "I will prepare a short summary."),
        ("A", "The deadline was moved to Friday."),
        ("B", "We will need to prioritize tasks."),
        ("A", "There is a typo on slide three."),
        ("B", "I will correct it before the meeting."),
        ("A", "Stakeholders want clearer numbers."),
        ("B", "I can add a chart to explain it."),
        ("A", "We should consider the long-term impact."),
        ("B", "I agree that short-term gains can mislead."),
        ("A", "The data suggests a different conclusion."),
        ("B", "Let's examine the methodology carefully."),
        ("A", "Ethically, we must be transparent."),
        ("B", "Transparency builds trust with the public."),
        ("A", "The treaty could reshape regional trade."),
        ("B", "Diplomats are negotiating the final clauses."),
        ("A", "One might question the underlying premise."),
        ("B", "Yet the counterargument deserves equal weight."),
    ]
    # Pair into A/B beats
    pairs = []
    for i in range(0, len(beats) - 1, 2):
        pairs.append((beats[i], beats[i + 1]))
    return pairs


BEAT_POOL = _beat_pool()


def _fill(text, ctx):
    for key, val in ctx.items():
        text = text.replace("{" + key + "}", str(val))
    return text


def _build_context(level, cat_id, lesson_num):
    n = lesson_num
    return {
        "place": PLACES[(n * 7 + hash(cat_id)) % len(PLACES)],
        "name": NAMES[(n * 3 + hash(level)) % len(NAMES)],
        "time": TIMES[(n * 5) % len(TIMES)],
        "food": FOODS[(n * 11) % len(FOODS)],
        "item": ITEMS[(n * 13) % len(ITEMS)],
        "mood": MOODS[(n * 2) % len(MOODS)],
        "activity": ACTIVITIES[(n * 17) % len(ACTIVITIES)],
        "ctx_activity": ACTIVITIES[(n * 19) % len(ACTIVITIES)],
        "weather": WEATHER[(n * 4) % len(WEATHER)],
        "color": COLORS[(n * 6) % len(COLORS)],
        "number": NUMBERS_CTX[(n * 8) % len(NUMBERS_CTX)],
        "topic": list(LEVELS[level]["categories"].values())[(n) % len(LEVELS[level]["categories"])],
    }


def _generate_title(cat_id, lesson_num, ctx):
    templates = TITLE_TEMPLATES.get(cat_id, ["Lesson {number}"])
    tpl = templates[lesson_num % len(templates)]
    ctx_copy = dict(ctx)
    ctx_copy["number"] = str(lesson_num + 1)
    return _fill(tpl, ctx_copy)


def _generate_dialogue(level, cat_id, lesson_num, target_lines):
    ctx = _build_context(level, cat_id, lesson_num)
    dialogue = []
    for speaker, text in _level_opener(level, ctx):
        dialogue.append((speaker, _fill(text, ctx)))

    beats_needed = max(4, (target_lines - len(dialogue) - 2) // 2)
    rng = random.Random((hash(level) ^ hash(cat_id) ^ lesson_num) & 0xFFFFFFFF)
    beat_indices = list(range(len(BEAT_POOL)))
    rng.shuffle(beat_indices)
    selected = beat_indices[:beats_needed]

    for bi in selected:
        a_line, b_line = BEAT_POOL[bi]
        dialogue.append((a_line[0], _fill(a_line[1], ctx)))
        dialogue.append((b_line[0], _fill(b_line[1], ctx)))
        if len(dialogue) >= target_lines - 2:
            break

    for speaker, text in _level_closer(level, ctx):
        if len(dialogue) >= target_lines:
            break
        dialogue.append((speaker, _fill(text, ctx)))

    # Trim to target if over
    while len(dialogue) > target_lines:
        dialogue.pop(-3)  # remove a middle beat, keep closer

    # Pad if under minimum
    pad_idx = 0
    while len(dialogue) < MIN_LINES:
        a_line, b_line = BEAT_POOL[pad_idx % len(BEAT_POOL)]
        dialogue.insert(-2, (b_line[0], _fill(b_line[1], ctx)))
        dialogue.insert(-2, (a_line[0], _fill(a_line[1], ctx)))
        pad_idx += 1

    return dialogue, ctx


def _dialogue_fingerprint(dialogue):
    return "|".join(t for _, t in dialogue)


def _extract_vocab_from_dialogue(dialogue, limit=10):
    words = []
    seen = set()
    for _s, text in dialogue:
        for w in re.findall(r"[A-Za-z']{4,}", text):
            low = w.lower().strip("'")
            if low in STOP_WORDS or low in seen or len(low) < 4:
                continue
            seen.add(low)
            words.append(low)
            if len(words) >= limit:
                return words
    return words


def _build_vocabulary(cat_id, dialogue, lesson_num):
    glossary = CATEGORY_VOCAB.get(cat_id, CATEGORY_VOCAB["greetings"])
    vocab = []
    used = set()
    for i in range(3):
        entry = glossary[(lesson_num * 3 + i) % len(glossary)]
        w, d = entry[0], entry[1]
        if w not in used:
            vocab.append({"word": w, "definition": d})
            used.add(w)
    for w in _extract_vocab_from_dialogue(dialogue):
        if len(vocab) >= VOCAB_COUNT:
            break
        if w not in used:
            vocab.append({
                "word": w,
                "definition": f"A word used in this lesson about {cat_id.replace('_', ' ')}.",
            })
            used.add(w)
    idx = 0
    while len(vocab) < VOCAB_COUNT:
        entry = glossary[idx % len(glossary)]
        if entry[0] not in used:
            vocab.append({"word": entry[0], "definition": entry[1]})
            used.add(entry[0])
        idx += 1
    return vocab[:VOCAB_COUNT]


GRAMMAR_BY_LEVEL = {
    "a1": [
        ("Choose the correct verb: She ___ fine today.", ["is", "are", "am"], 0),
        ("Which is a correct question?", ["How are you?", "How you are?", "How is you?"], 0),
        ("Fill in: I ___ going to the store.", ["am", "is", "are"], 0),
        ("Choose the correct form: They ___ happy.", ["are", "is", "am"], 0),
        ("Article: I have ___ umbrella.", ["an", "a", "the"], 0),
        ("Plural: two ___", ["books", "book", "bookes"], 0),
        ("Negative: I ___ hungry.", ["am not", "is not", "are not"], 0),
        ("Possessive: This is ___ bag.", ["my", "me", "I"], 0),
    ],
    "a2": [
        ("Past tense: Yesterday I ___ to the market.", ["went", "go", "going"], 0),
        ("Future: I ___ visit my friend tomorrow.", ["will", "was", "has"], 0),
        ("Comparative: This book is ___ than that one.", ["better", "good", "best"], 0),
        ("Past continuous: They ___ eating when I arrived.", ["were", "was", "are"], 0),
        ("Countable: How ___ apples do you need?", ["many", "much", "lot"], 0),
        ("Preposition: The cat is ___ the table.", ["under", "between", "among"], 0),
    ],
    "b1": [
        ("Present perfect: I ___ lived here for two years.", ["have", "has", "had"], 0),
        ("First conditional: If it rains, we ___ stay inside.", ["will", "would", "stayed"], 0),
        ("Modal: You ___ wear a seatbelt.", ["should", "may", "might"], 0),
        ("Relative clause: The person ___ called is my colleague.", ["who", "which", "where"], 0),
        ("Passive: The letter ___ sent yesterday.", ["was", "were", "is"], 0),
    ],
    "b2": [
        ("Passive voice: The report ___ finished yesterday.", ["was", "were", "is"], 0),
        ("Reported speech: He said he ___ tired.", ["was", "is", "be"], 0),
        ("Second conditional: If I ___ more time, I would help.", ["had", "have", "has"], 0),
        ("Gerund: She avoided ___ the question.", ["answering", "answer", "answered"], 0),
        ("Future perfect: By June, we ___ the project.", ["will have completed", "complete", "completed"], 0),
    ],
    "c1": [
        ("Advanced tense: By next year, she ___ completed the project.", ["will have", "will", "has"], 0),
        ("Subjunctive-style: It is essential that he ___ on time.", ["be", "is", "was"], 0),
        ("Complex clause: ___ the evidence, the claim remains weak.", ["Given", "Give", "Giving"], 0),
        ("Formal: The committee ___ to review the proposal.", ["intends", "intend", "intending"], 0),
        ("Inversion: Rarely ___ such a result.", ["do we see", "we see", "we saw"], 0),
    ],
    "c2": [
        ("Inversion: Never before ___ such a complex debate.", ["had we witnessed", "we had witnessed", "we have witnessed"], 0),
        ("Nuanced modal: You ___ have informed us earlier.", ["might", "can", "shall"], 0),
        ("Connector: ___ sophisticated the argument, flaws remain.", ["However", "Therefore", "Because"], 0),
        ("Precision: The speaker's tone was deliberately ___.", ["measured", "measure", "measuring"], 0),
        ("Subtle aspect: He ___ been considering resignation for months.", ["had", "has", "have"], 0),
    ],
}


def _make_quiz(title, dialogue, level, vocabulary):
    """Exactly 5 quiz questions: 2 reading, 2 vocabulary, 1 grammar."""
    lines_b = [t for s, t in dialogue if s == "B"]
    mid_b = lines_b[len(lines_b) // 2] if lines_b else ""

    activity = "Talking and sharing information"
    for _s, text in dialogue:
        low = text.lower()
        for key, label in [
            ("library", "Going to the library"),
            ("coffee", "Meeting for food or drink"),
            ("lunch", "Meeting for food or drink"),
            ("shop", "Shopping"),
            ("store", "Shopping"),
            ("work", "Work or office matters"),
            ("study", "Studying or school"),
            ("hospital", "A health appointment"),
            ("train", "Travel by train"),
            ("meeting", "A work meeting"),
        ]:
            if key in low:
                activity = label
                break

    q_reading_1 = {
        "type": "reading",
        "question": "What is the main topic of this conversation?",
        "options": [title, "A unrelated sports game", "Only silent gestures"],
        "correct": 0,
    }
    q_reading_2 = {
        "type": "reading",
        "question": "Which activity or subject appears in the dialogue?",
        "options": [activity, "Building a spaceship", "Swimming across an ocean"],
        "correct": 0,
    }
    if level in ("b1", "b2", "c1", "c2"):
        q_reading_2["question"] = "Which summary best describes this exchange?"
        q_reading_2["options"] = [
            "Speakers discuss relevant matters in a natural way",
            "One speaker refuses to participate",
            "The dialogue has no connection to the title",
        ]
        q_reading_2["correct"] = 0

    v1 = vocabulary[0]
    v2 = vocabulary[1]
    distractors = [v["word"] for v in vocabulary[2:]] + ["table", "window", "river"]
    q_vocab_1 = {
        "type": "vocabulary",
        "question": f'What does "{v1["word"]}" mean in this lesson?',
        "options": [
            v1["definition"],
            "A type of vehicle only",
            "A color with no meaning",
        ],
        "correct": 0,
    }
    q_vocab_2 = {
        "type": "vocabulary",
        "question": f'Which definition matches "{v2["word"]}"?',
        "options": [
            v2["definition"],
            distractors[(hash(title) + 1) % len(distractors)].capitalize() + " only",
            "None of the above",
        ],
        "correct": 0,
    }

    pool = GRAMMAR_BY_LEVEL.get(level, GRAMMAR_BY_LEVEL["a1"])
    g = pool[abs(hash(title + level)) % len(pool)]
    q_grammar = {
        "type": "grammar",
        "question": g[0],
        "options": list(g[1]),
        "correct": g[2],
    }

    return [q_reading_1, q_reading_2, q_vocab_1, q_vocab_2, q_grammar]


def _lessons_per_category(total, num_cats):
    base = total // num_cats
    rem = total % num_cats
    return [base + (1 if i < rem else 0) for i in range(num_cats)]


def _generate_lesson(level_id, cat_id, cat_name, lesson_idx, seen_dialogues):
    """Generate one unique lesson; lesson_idx is 1-based within category."""
    target_lines = MIN_LINES + (lesson_idx % (MAX_LINES - MIN_LINES + 1))
    attempt = 0
    while attempt < 50:
        num = lesson_idx * 1000 + attempt
        dialogue, ctx = _generate_dialogue(level_id, cat_id, num, target_lines)
        fp = _dialogue_fingerprint(dialogue)
        if fp not in seen_dialogues:
            seen_dialogues.add(fp)
            title = _generate_title(cat_id, lesson_idx + attempt, ctx)
            vocabulary = _build_vocabulary(cat_id, dialogue, lesson_idx)
            quiz = _make_quiz(title, dialogue, level_id, vocabulary)
            lesson_id = f"{level_id}-{cat_id}-{lesson_idx}"
            return {
                "id": lesson_id,
                "title": title,
                "dialogue": [{"speaker": s, "text": t} for s, t in dialogue],
                "vocabulary": vocabulary,
                "quiz": quiz,
            }
        attempt += 1
    # Fallback with extra unique suffix
    title = f"{cat_name} Conversation {lesson_idx}"
    vocabulary = _build_vocabulary(cat_id, dialogue, lesson_idx)
    return {
        "id": f"{level_id}-{cat_id}-{lesson_idx}",
        "title": title,
        "dialogue": [{"speaker": s, "text": t} for s, t in dialogue],
        "vocabulary": vocabulary,
        "quiz": _make_quiz(title, dialogue, level_id, vocabulary),
    }


def build_level(level_id):
    meta = LEVELS[level_id]
    categories = []
    lesson_count = 0
    line_count = 0
    seen_dialogues = set()
    counts = _lessons_per_category(LESSONS_PER_LEVEL, len(meta["categories"]))

    for (cat_id, cat_name), count in zip(meta["categories"].items(), counts):
        lessons = []
        for idx in range(1, count + 1):
            lesson = _generate_lesson(level_id, cat_id, cat_name, idx, seen_dialogues)
            lessons.append(lesson)
            lesson_count += 1
            line_count += len(lesson["dialogue"])

        categories.append({
            "id": cat_id,
            "name": cat_name,
            "lessons": lessons,
        })

    return {
        "level": level_id,
        "name": meta["name"],
        "description": meta["description"],
        "categories": categories,
        "stats": {"lessons": lesson_count, "lines": line_count},
    }


def build_index():
    levels = []
    for level_id, meta in LEVELS.items():
        levels.append({
            "id": level_id,
            "name": meta["name"],
            "description": meta["description"],
            "file": f"{level_id}.json",
            "categories": [
                {"id": cid, "name": cname}
                for cid, cname in meta["categories"].items()
            ],
        })
    return {"version": 2, "levels": levels}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    grand_lessons = 0
    grand_lines = 0

    for level_id in LEVELS:
        payload = build_level(level_id)
        grand_lessons += payload["stats"]["lessons"]
        grand_lines += payload["stats"]["lines"]
        out_path = os.path.join(OUT_DIR, f"{level_id}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"Wrote {out_path}: {payload['stats']['lessons']} lessons, {payload['stats']['lines']} lines")

    index = build_index()
    index["stats"] = {"lessons": grand_lessons, "lines": grand_lines}
    index_path = os.path.join(OUT_DIR, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"Wrote {index_path}")
    print(f"TOTAL: {grand_lessons} lessons, {grand_lines} dialogue lines")


if __name__ == "__main__":
    main()
