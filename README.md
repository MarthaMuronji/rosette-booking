# Rosette Wellness Booking System

A production Django booking platform built and maintained for a Dubai-based mobile massage business.

**Live site:** [roxannawellness.com](https://roxannawellness.com)

## Overview

A full-stack booking system covering the entire appointment lifecycle — from a client's initial request through therapist approval, client confirmation, and payment — with real-time notifications and a redesigned booking experience built to reduce abandonment.

## Features

- **Full appointment lifecycle** — request → therapist approval → client confirmation → payment
- **Real-time notifications** — WhatsApp and web push integration keeps clients and therapists updated at every step
- **Single-source-of-truth pricing** — one pricing architecture shared across the booking system and marketing site, eliminating price-sync bugs between templates
- **Membership & package system** — session tracking, expiry, and progress visualization for repeat clients
- **Dynamic pricing engine** — zone-based and add-on pricing supporting 9+ service types
- **Goal-based booking UX** — treatment triage, a promoted "hero" service, and upfront pricing to reduce client confusion
- **Security hardening** — rate-limited login with automatic lockout, session expiry on browser close, and remediation of a Row-Level Security misconfiguration that had exposed client data
- **Cost-optimized infrastructure** — migrated from Railway to Render + Supabase (PostgreSQL), reducing hosting costs to $0/month with automated uptime monitoring

## Tech stack

Django · PostgreSQL (Supabase) · JavaScript · HTML/CSS · Render (hosting) · WhatsApp Business API · Web Push API

## Getting started locally

```bash
# Clone the repo
git clone https://github.com/MarthaMuronji/rosette-wellness.git
cd rosette-wellness

# Set up a virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env  # then fill in your own values

# Run migrations
python manage.py migrate

# Start the development server
python manage.py runserver
```

## Screenshots

*(Add 2–3 screenshots here — the booking flow, the membership/package view, and the pricing page work well)*

## About this project

Built and maintained as ongoing client work for a real business, with direct collaboration on priorities and improvements based on live user feedback.
