
import sys
import os
sys.path.append('../')

# Mock dotenv for debug purposes if missing
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(), override=True)
except ImportError:
    print("Warning: dotenv not found, proceeding without it.")


import gradio as gr
from src.rubrics import RubricsFlow

print(f'📦 Gradio version: {gr.__version__}')

# Dummy globals
TARGET_TEXT = "Test text for rubrics generation."
EVALUATION_PURPOSE = "Testing"
EVALUATION_RUBRICS = ""

# Lazy init logic from notebook
rubrics_flow = None
def get_rubrics_flow():
    global rubrics_flow
    if rubrics_flow is None:
        rubrics_flow = RubricsFlow()
        print("RubricsFlow initialized.")
    return rubrics_flow

def on_generate_rubrics(manual_input):
    print("Generating rubrics (mock)...")
    if not TARGET_TEXT:
        return "❌ No text", "", gr.update(interactive=False)
    
    rf = get_rubrics_flow()
    rf.set_context(TARGET_TEXT, EVALUATION_PURPOSE)
    # Mocking generation to avoid LLM call if possible, or we let it fail if env is missing
    # But usually we just want to test UI launch
    return "✅ Criteria generated!", "Mock Rubrics Content", gr.update(interactive=True)

with gr.Blocks() as step25_demo:
    gr.Markdown("## Step 2.5: Evaluation Criteria (Rubrics)")
    
    with gr.Tabs():
        with gr.Tab("✍️ Manual Input"):
            manual_input = gr.Textbox(label="Manual Input")
            use_manual_btn = gr.Button("Use Manual")
        
        with gr.Tab("🤖 AI Generation"):
            generate_btn = gr.Button("Generate")
    
    edit_area = gr.Textbox(label="Editable")
    confirm_btn = gr.Button("Confirm")
    status_msg = gr.Markdown()
    
    generate_btn.click(
        fn=on_generate_rubrics,
        inputs=[manual_input],
        outputs=[status_msg, edit_area, confirm_btn]
    )

print("Launching Step 2.5 Debug Interface...")
try:
    # Mimic the fixed launch command
    step25_demo.launch(height=800, inline=True, quiet=False, debug=False, show_error=True)
    print("✅ Launch command executed without error.")
except Exception as e:
    print(f"❌ Launch failed: {e}")
    import traceback
    traceback.print_exc()

# Keep script alive briefly to ensure async threads might start
import time
time.sleep(2)
print("Debug script finished.")
