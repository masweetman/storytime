// Store user selections
const selections = {
    character: null,
    setting: null,
    colour: null
};

// Get all choice buttons
const choiceButtons = document.querySelectorAll('.choice-btn');
const colorButtons = document.querySelectorAll('.color-btn');
const generateBtn = document.getElementById('generate-btn');
const loadingDiv = document.getElementById('loading');
const errorDiv = document.getElementById('error');

// Add event listeners to character and setting buttons
choiceButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        const type = btn.dataset.type;
        const value = btn.dataset.value;

        // Remove previous selection in this category
        document.querySelectorAll(`.choice-btn[data-type="${type}"]`).forEach(b => {
            b.classList.remove('selected');
        });

        // Add selection to clicked button
        btn.classList.add('selected');
        selections[type] = value;

        // Update display
        updateSelectionDisplay();
        checkAllSelected();
    });
});

// Add event listeners to color buttons
colorButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        // Remove previous color selection
        document.querySelectorAll('.color-btn').forEach(b => {
            b.classList.remove('selected');
        });

        // Add selection to clicked button
        btn.classList.add('selected');
        selections['colour'] = btn.dataset.value;

        // Update display
        updateSelectionDisplay();
        checkAllSelected();
    });
});

// Update the selection display text
function updateSelectionDisplay() {
    const characterSpan = document.querySelector('#character-display span');
    const settingSpan = document.querySelector('#setting-display span');
    const colourSpan = document.querySelector('#colour-display span');

    characterSpan.textContent = selections.character || 'Not picked yet';
    settingSpan.textContent = selections.setting || 'Not picked yet';
    colourSpan.textContent = selections.colour || 'Not picked yet';
}

// Check if all selections are made and enable generate button
function checkAllSelected() {
    if (selections.character && selections.setting && selections.colour) {
        generateBtn.disabled = false;
    } else {
        generateBtn.disabled = true;
    }
}

// Generate story when button is clicked
generateBtn.addEventListener('click', generateStory);

async function generateStory() {
    // Show loading state
    loadingDiv.classList.remove('hidden');
    errorDiv.classList.add('hidden');
    generateBtn.disabled = true;

    try {
        // Call the backend API
        const response = await fetch('/api/generate-story', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                character: selections.character,
                setting: selections.setting,
                colour: selections.colour
            })
        });

        const data = await response.json();

        if (data.success) {
            // Store the story data in sessionStorage
            sessionStorage.setItem('storyData', JSON.stringify({
                story: data.story,
                images: data.images,
                character: data.character,
                setting: data.setting,
                colour: data.colour
            }));

            // Navigate to story page
            window.location.href = '/story';
        } else {
            showError(data.error);
        }
    } catch (error) {
        showError('Something went wrong. Is Ollama running?');
        console.error('Error:', error);
    } finally {
        loadingDiv.classList.add('hidden');
        generateBtn.disabled = false;
    }
}

function showError(message) {
    errorDiv.textContent = '❌ ' + message;
    errorDiv.classList.remove('hidden');
}

// Handle story page route
if (window.location.pathname === '/story') {
    // This is handled by the story.html template
    document.addEventListener('DOMContentLoaded', () => {
        const storyData = JSON.parse(sessionStorage.getItem('storyData') || '{}');
        if (!storyData.story) {
            window.location.href = '/';
        }
    });
}
