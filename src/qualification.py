
import gradio as gr
import statistics
from src.utils import parse_json_output
from src.llm_provider import LLMProvider
from src.agents import QUALIFICATION_PROMPT

class QualificationFlow:
    def __init__(self):
        self.llm = LLMProvider()
        self.history = [] # Chatbot history (list of dicts for internal, list of lists for gradio legacy?) 
        # Gradio Chatbot expects list of [user, bot] lists OR list of message dicts if type="messages". 
        # The notebook used type="messages" implicitly in code ("role": "assistant"). 
        # Wait, the notebook code returned `[{"role": "assistant"...}]`.
        
        self.internal_history = [] # List of strings for prompt
        self.scores = []
        self.target_text = ""
        self.max_rounds = 50
        self.current_round = 0
        self.human_competency_score = 0
        self.reason = ""
        self.evaluation_purpose = "General Assessment"
        
        # New State Variables for 3-Phase System
        self.current_phase = "1" 
        self.score_accumulator = 0.0
        self.score_accumulator = 0.0
        self.score_history = [] # To track progression [50, 55, 52, ...]
        self.asked_questions = [] # Track asked questions to prevent repetition
        self.previous_difficulty = 0 # Track difficulty of the question JUST asked

    def set_target_text(self, text, purpose="General Assessment"):
        self.target_text = text
        self.evaluation_purpose = purpose

    def get_score(self):
        return self.human_competency_score

    def on_start_interview(self, max_rounds):
        self.max_rounds = int(max_rounds)
        self.internal_history = []
        self.scores = []
        self.current_round = 0
        self.human_competency_score = 0
        self.reason = ""
        
        # Reset new state
        self.current_phase = "1"
        self.score_accumulator = 0.0
        self.score_accumulator = 0.0
        self.score_history = []
        self.asked_questions = []
        self.previous_difficulty = 0
        
        if not self.target_text:
            return [{"role": "assistant", "content": "❌ Error: No Target Text found. Please complete Step 1 first."}], gr.update(interactive=False)
            
        print(f"DEBUG: Starting Interview. Target Text ({len(self.target_text)} chars): {self.target_text[:50]}...")

        try:
            # Format prompt
            # Format prompt
            try:
                # Initial Prompt - Phase 1 starts
                prompt = QUALIFICATION_PROMPT.format(
                    target_text=self.target_text, 
                    evaluation_purpose=self.evaluation_purpose, 
                    history="", 
                    current_phase="1",
                    current_score=0,
                    asked_questions="None"
                )
            except KeyError:
                # Fallback
                prompt = QUALIFICATION_PROMPT.format(
                    target_text=self.target_text, 
                    history="", 
                    current_phase="1",
                    current_score=0,
                    asked_questions="None"
                )
            
            response = self.llm.generate("qwen-max", [{"role": "user", "content": prompt}])
            data = parse_json_output(response)
            
            status = data.get("status")
            score = data.get("score")
            
            # Record initial score if present
            # Record initial score if present
            if score is not None:
                try:
                    val = float(score)
                    # Only record if it's a real score (not a placeholder 0 while asking)
                    if status != "asking" or val > 0:
                        self.scores.append(val)
                except:
                    pass

            if status == "asking":
                question = data.get("question")
                difficulty = data.get("difficulty")
                # Update tracker
                if difficulty:
                    self.previous_difficulty = int(difficulty)
                
                self.internal_history.append(f"AI: {question}")
                self.asked_questions.append(question)
                self.current_round += 1
                # Format for Gradio 6.x (Default = messages?)
                return [{"role": "assistant", "content": f"🤖 Examiner: {question}"}], gr.update(interactive=True)
            else:
                final_score = data.get("score", 0)
                reason = data.get("reason", "Evaluation ended.")
                self.human_competency_score = final_score
                self.reason = reason
                return [{"role": "assistant", "content": f"✅ Assessment Complete.\n**Score:** {final_score}\n**Reason:** {reason}"}], gr.update(interactive=False)
                
        except Exception as e:
            return [{"role": "assistant", "content": f"Error calling LLM: {str(e)}"}], gr.update(interactive=False)

    def on_user_reply(self, user_input, history):
        if not user_input.strip():
            return history, ""
        
        if history is None:
            history = []
            
        # Append User Message to UI history (for messages format)
        history.append({"role": "user", "content": user_input})
        
        # Append to Internal History
        self.internal_history.append(f"User: {user_input}")
        
        history_str = "\n".join(self.internal_history)
        
        # Prepare forbidden questions string
        asked_questions_str = "\n- ".join(self.asked_questions) if self.asked_questions else "None"

        try:
            try:
                # Pass current_score to the prompt
                prompt = QUALIFICATION_PROMPT.format(
                    target_text=self.target_text, 
                    evaluation_purpose=self.evaluation_purpose, 
                    history=history_str,
                    current_phase=self.current_phase,
                    current_score=f"{self.score_accumulator:.1f}",
                    asked_questions=asked_questions_str
                )
            except KeyError:
                prompt = QUALIFICATION_PROMPT.format(
                    target_text=self.target_text, 
                    history=history_str,
                    current_phase=self.current_phase,
                    current_score=f"{self.score_accumulator:.1f}",
                    asked_questions=asked_questions_str
                )
            
            response = self.llm.generate("qwen-max", [{"role": "user", "content": prompt}])
            data = parse_json_output(response)
            
            # DEBUG: Print what AI returned
            print(f"DEBUG AI Response: {data}")
            
            # Parse New Fields
            status = data.get("status")
            new_phase = data.get("phase", self.current_phase)
            base_score = data.get("base_score")
            # score_delta is DEPRECATED. We calculate it.
            answer_quality = data.get("answer_quality", "fail") # pass or fail only
            
            question = data.get("question", "")
            reason = data.get("reason", "")
            difficulty = data.get("difficulty") # Integer 1, 3, 5, 10 for the NEXT question
            self_rating = data.get("self_rating") # Phase 3 extraction

            # DEBUG: Print parsed values
            print(f"DEBUG: phase={new_phase}, answer_quality={answer_quality}, prev_diff={self.previous_difficulty}, current_score={self.score_accumulator}")

            # --- SCORING LOGIC ---
            
            # 1. Detect Phase Change or Base Score Setting (Phase 1 -> 2)
            if base_score is not None:
                try:
                    b_score = float(base_score)
                    if self.current_phase == "1" or self.score_accumulator == 0:
                        self.score_accumulator = b_score
                        # Log the base score set event
                        self.internal_history.append(f"[System]: Base Score set to {b_score}")
                        print(f"DEBUG: Base score set to {b_score}")
                except:
                    pass

            # 2. Apply Score Delta based on Previous Question Difficulty
            # We use self.previous_difficulty (set in the LAST turn)
            calculated_delta = 0
            if self.current_phase == "2" or self.current_phase == "3" or new_phase == "2" or new_phase == "3":
                 if answer_quality == "pass":
                     calculated_delta = float(self.previous_difficulty)
                 elif answer_quality == "fail":
                     calculated_delta = -float(self.previous_difficulty)
                 # neutral = 0
            
            print(f"DEBUG: calculated_delta={calculated_delta}")
            
            if calculated_delta != 0:
                 self.score_accumulator += calculated_delta
                 self.score_accumulator = max(0, min(100, self.score_accumulator))
                 print(f"DEBUG: Score updated to {self.score_accumulator}")

            # Update Difficulty for NEXT turn
            if difficulty is not None:
                 try:
                     self.previous_difficulty = int(difficulty)
                 except:
                     pass

            # Update Phase
            self.current_phase = new_phase
            self.score_history.append(self.score_accumulator)

            # --- STOPPING LOGIC ---
            
            should_stop = False
            stop_reason = ""
            
            # Condition A: Max Rounds
            if self.current_round >= self.max_rounds:
                should_stop = True
                stop_reason = f"Max rounds ({self.max_rounds}) reached."
            
            # Condition B: Phase 3 Completed (User explicitly quits or LLM finishes Phase 3)
            # We strictly wait for Phase 3 completion.
            if status == "finished":
                if self.current_phase == "3" or self.current_phase == "3_done":
                     should_stop = True
                     stop_reason = "Assessment Phases Completed."
                else:
                    # If LLM tries to finish in Phase 1 or 2, force it to continue unless user quit (which is handled by logic that LLM should stick to)
                    # For now we trust LLM 'finished' status IF it implies user quit.
                    # But per user request "completed 3 stages to end", we generally enforce phases.
                    # Let's assume if status is finished, it's valid, but we prefer 3 phases.
                    should_stop = True # Allow finish if LLM decides so (likely user quit)
                    stop_reason = reason

            if not should_stop:
                self.internal_history.append(f"AI: {question}")
                self.asked_questions.append(question)
                self.current_round += 1
                
                # Add difficulty indicator and current score
                diff_str = f" [Diff: {difficulty}]" if difficulty else ""
                score_str = f"\n[current_score: {self.score_accumulator:.1f}]"
                
                history.append({"role": "assistant", "content": f"🤖 Examiner: {question}{diff_str}{score_str}"})
                return history, ""
            
            else:
                # FINALIZATION
                
                # Phase 3 Averaging: If self_rating is present, average it with accumulated score
                final_score = self.score_accumulator
                if self_rating is not None:
                    try:
                        s_rating = float(self_rating)
                        # Average: (Probe Score + Self Rating) / 2
                        final_score = (self.score_accumulator + s_rating) / 2
                        self.score_history.append(final_score) # Log the final jump
                        self.internal_history.append(f"[System]: Averaging Probe ({self.score_accumulator}) + Self-Rating ({s_rating}) = {final_score}")
                    except:
                        pass
                
                self.human_competency_score = final_score
                self.reason = reason if reason else stop_reason
                
                # History Visualization
                score_progression = " -> ".join([f"{s:.1f}" for s in self.score_history])
                
                final_msg = f"""✅ Assessment Complete.
**Final Score:** {self.human_competency_score:.2f}
**Reason:** {self.reason}

**Score Progression:**
{score_progression}

You can now proceed to Step 3."""
                
                history.append({"role": "assistant", "content": final_msg})
                return history, ""

        except Exception as e:
            history.append({"role": "assistant", "content": f"Error calling LLM: {str(e)}"})
            return history, ""
