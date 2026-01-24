import threading
from typing import Dict
from rich.console import Console
from rich.table import Table

class CostTracker:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(CostTracker, cls).__new__(cls)
                    cls._instance.reset()
        return cls._instance
    
    def reset(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.model_usage: Dict[str, dict] = {}
        
    def track_usage(self, model: str, input_tokens: int, output_tokens: int, cost: float = 0.0):
        with self._lock:
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_cost += cost
            
            if model not in self.model_usage:
                self.model_usage[model] = {"input": 0, "output": 0, "cost": 0.0}
            
            self.model_usage[model]["input"] += input_tokens
            self.model_usage[model]["output"] += output_tokens
            self.model_usage[model]["cost"] += cost

    def print_summary(self):
        console = Console()
        table = Table(title="💰 LLM Cost & Usage Summary", show_header=True, header_style="bold green")
        table.add_column("Model", style="cyan")
        table.add_column("Input Tokens", justify="right")
        table.add_column("Output Tokens", justify="right")
        table.add_column("Est. Cost ($)", justify="right", style="green")
        
        for model, stats in self.model_usage.items():
            table.add_row(
                model,
                f"{stats['input']:,}",
                f"{stats['output']:,}",
                f"${stats['cost']:.4f}"
            )
            
        console.print("\n")
        console.print(table)
        console.print(f"\n[bold]Total Estimated Cost: [green]${self.total_cost:.4f}[/green][/bold]\n")

cost_tracker = CostTracker()
