import asyncio
import httpx

async def main():
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30.0) as client:
        # 1. Create session
        res = await client.post("/api/sessions", json={"target_url": "http://localhost:8001/mock_form.html"})
        print("Create session:", res.status_code, res.json())
        session_id = res.json()["id"]

        # 2. Step 1: Open browser
        res1 = await client.post(f"/api/agent/{session_id}/step")
        print("Step 1:", res1.status_code, res1.json()["status"], "page:", res1.json().get("current_page_title"))

        # 3. Step 2: Detect & map & confidence
        res2 = await client.post(f"/api/agent/{session_id}/step")
        state2 = res2.json()
        print("Step 2:", res2.status_code, state2["status"])
        print("Detected fields count:", len(state2.get("detected_fields", [])))
        print("Auto fill queue count:", len(state2.get("auto_fill_queue", [])))
        print("Human review queue count:", len(state2.get("human_review_queue", [])))
        for q in state2.get("human_review_queue", []):
            print("  HITL Field:", q["field_id"], "Answer:", q["answer"], "Reason:", q["reason"])

        # 4. Human review payload simulation
        answers = {}
        for q in state2.get("human_review_queue", []):
            answers[q["field_id"]] = q["answer"] or "Sample Answer"
        
        print("\nSubmitting human review with answers:", answers)
        res3 = await client.post(f"/api/agent/{session_id}/human-review", json={"answers": answers})
        state3 = res3.json()
        print("\nResume result status:", state3.get("status"))
        print("Validation errors:", state3.get("validation_errors"))
        print("Error message:", state3.get("error_message"))
        print("Auto fill queue remaining:", len(state3.get("auto_fill_queue", [])))
        print("Human review queue remaining:", len(state3.get("human_review_queue", [])))

if __name__ == "__main__":
    asyncio.run(main())
